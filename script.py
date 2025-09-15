import requests
import argparse
import os
import re
from datetime import datetime, timezone, timedelta
import matplotlib.pyplot as plt
from collections import defaultdict

# Assuming you have this local file for your custom classifier
from bug_classifier import GitHubBugClassifier

GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"

# --- Configuration ---
# Add the repository names you want to filter by into this list.
REPOSITORIES = [
    
]
# -------------------


def fetch_all_github_project_items(token, project_number, org=None, user=None):
    """
    Fetches all items from a GitHub ProjectV2 board, handling pagination.
    """
    if org:
        owner_type = "organization"
        owner_login = org
    elif user:
        owner_type = "user"
        owner_login = user
    else:
        raise ValueError("Either an organization or a user must be specified.")

    all_items = []
    has_next_page = True
    end_cursor = None

    print(f"Fetching all project items for project #{project_number} for {owner_type}: {owner_login}...")

    while has_next_page:
        # Added repository { name } to the query to enable filtering.
        query = f"""
        query GetProjectItems($owner_login: String!, $project_number: Int!, $end_cursor: String) {{
          {owner_type}(login: $owner_login) {{
            projectV2(number: $project_number) {{
              title
              items(first: 100, after: $end_cursor) {{
                pageInfo {{
                  hasNextPage
                  endCursor
                }}
                nodes {{
                  id
                  content {{
                    __typename
                    ... on Issue {{
                      title
                      url
                      number
                      body
                      createdAt
                      closedAt
                      repository {{
                        name
                      }}
                      assignees(first: 5) {{
                        nodes {{
                          login
                        }}
                      }}
                      labels(first: 10) {{
                        nodes {{
                          name
                        }}
                      }}
                    }}
                  }}
                }}
              }}
            }}
          }}
        }}
        """
        
        variables = {
            "owner_login": owner_login,
            "project_number": project_number,
            "end_cursor": end_cursor
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(GITHUB_GRAPHQL_URL, json={"query": query, "variables": variables}, headers=headers)
        
        if response.status_code != 200:
            print(f"Error: API request failed with status code {response.status_code}")
            print(f"Response: {response.text}")
            return None

        response_data = response.json()
        if "errors" in response_data:
            print(f"Error: GraphQL query returned errors: {response_data['errors']}")
            return None
            
        project_data = response_data.get("data", {}).get(owner_type, {}).get("projectV2")
        
        if not project_data:
            print("\n--- ERROR ---")
            print(f"Project not found. Please check the following:")
            print(f"1. The {owner_type} '{owner_login}' is correct.")
            print(f"2. Project number '{project_number}' exists for that {owner_type}.")
            print(f"3. Your token has 'read:project' permissions for this project.")
            print("--------------\n")
            return None

        items_page = project_data.get("items", {})
        all_items.extend(items_page.get("nodes", []))
        
        page_info = items_page.get("pageInfo", {})
        has_next_page = page_info.get("hasNextPage", False)
        end_cursor = page_info.get("endCursor")
        
        print(f"  ...fetched {len(all_items)} items so far.")

    print(f"Successfully fetched a total of {len(all_items)} items from project '{project_data.get('title')}'.")
    return all_items

def is_bug(issue):
    """
    Determines if an issue is likely a bug by checking its labels, title, and body.
    """
    bug_keywords = ['bug', 'fix', 'issue', 'error', 'crash', 'fail', 'unable']
    
    issue_labels = issue.get("labels", {}).get("nodes", [])
    for label in issue_labels:
        if 'bug' in label['name'].lower(): # and ('documentation' not in label['name'].lower() and 'general' not in label['name'].lower()):
            return True
            
    title = issue.get('title', '').lower()
    if any(re.search(r'\b' + keyword + r'\b', title) for keyword in bug_keywords):
        return True
        
    body = issue.get('body', '').lower()
    if any(re.search(r'\b' + keyword + r'\b', body) for keyword in bug_keywords):
        return True
        
    return False

def is_bug_simple(issue):
    """Placeholder for your custom bug classifier."""
    classifier = GitHubBugClassifier()
    result = classifier.classify_single_issue(issue, threshold=2.0)
    return result['is_bug']

def analyze_bugs_by_month(items, cutoff_date):
    """
    Analyzes bug reports by month to calculate count/average resolution time
    and groups the raw bug data for reporting.
    """
    monthly_metrics = defaultdict(lambda: {"reported_count": 0, "closed_count": 0, "resolution_times": []})
    monthly_bugs_raw = defaultdict(list)

    for item in items:
        issue = item.get("content")
        
        if not (issue and issue.get("__typename") == "Issue"):
            continue
            
        created_at = datetime.fromisoformat(issue['createdAt'].replace('Z', '+00:00'))
        if created_at < cutoff_date:
            continue

        if is_bug(issue) or is_bug_simple(issue):
            # Count reported bugs by creation month
            created_month_key = created_at.strftime("%Y-%m")
            monthly_bugs_raw[created_month_key].append(issue)
            monthly_metrics[created_month_key]["reported_count"] += 1

            # Count closed bugs by closure month
            if issue.get('closedAt'):
                closed_at = datetime.fromisoformat(issue['closedAt'].replace('Z', '+00:00'))
                closed_month_key = closed_at.strftime("%Y-%m")
                
                # Only count closed bugs if they were closed after the cutoff date
                if closed_at >= cutoff_date:
                    monthly_metrics[closed_month_key]["closed_count"] += 1
                
                # Resolution time calculation (for bugs created after cutoff)
                resolution_time = closed_at - created_at
                monthly_metrics[created_month_key]["resolution_times"].append(resolution_time.total_seconds())

    final_metrics = {}
    for month, data in sorted(monthly_metrics.items()):
        avg_resolution_days = 0
        if data["resolution_times"]:
            avg_seconds = sum(data["resolution_times"]) / len(data["resolution_times"])
            avg_resolution_days = avg_seconds / (3600 * 24)
        
        final_metrics[month] = {
            "reported_count": data["reported_count"],
            "closed_count": data["closed_count"],
            "avg_resolution_days": avg_resolution_days
        }
        
    return final_metrics, monthly_bugs_raw

def generate_chart(metrics, output_filename, cutoff_date):
    """
    Generates and saves a bar chart with reported/closed bugs and a line graph for avg resolution time.
    """
    if not metrics:
        print("No metrics to plot for chart.")
        return

    months = list(metrics.keys())
    reported_counts = [data['reported_count'] for data in metrics.values()]
    closed_counts = [data['closed_count'] for data in metrics.values()]
    avg_resolution = [data['avg_resolution_days'] for data in metrics.values()]

    fig, ax1 = plt.subplots(figsize=(14, 8))

    # Bar width and positions
    bar_width = 0.35
    x_pos = range(len(months))
    x_reported = [x - bar_width/2 for x in x_pos]
    x_closed = [x + bar_width/2 for x in x_pos]

    # Create bars for reported and closed bugs
    color_reported = 'tab:blue'
    color_closed = 'tab:green'
    
    bars1 = ax1.bar(x_reported, reported_counts, bar_width, color=color_reported, 
                    label='Bugs Reported', alpha=0.8)
    bars2 = ax1.bar(x_closed, closed_counts, bar_width, color=color_closed, 
                    label='Bugs Closed', alpha=0.8)

    ax1.set_xlabel('Month')
    ax1.set_ylabel('Number of Bugs', color='black')
    ax1.set_xticks(x_pos)
    ax1.set_xticklabels(months, rotation=45)
    ax1.tick_params(axis='x', rotation=45)

    # Add value labels on top of bars
    for bar in bars1:
        height = bar.get_height()
        if height > 0:
            ax1.annotate(f'{int(height)}',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 3),  # 3 points vertical offset
                        textcoords="offset points",
                        ha='center', va='bottom', fontsize=9)
    
    for bar in bars2:
        height = bar.get_height()
        if height > 0:
            ax1.annotate(f'{int(height)}',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 3),  # 3 points vertical offset
                        textcoords="offset points",
                        ha='center', va='bottom', fontsize=9)

    # Create second y-axis for resolution time
    ax2 = ax1.twinx()
    color_resolution = 'tab:red'
    line = ax2.plot(x_pos, avg_resolution, color=color_resolution, marker='o', 
                   linestyle='-', linewidth=2, markersize=6, 
                   label='Avg. Resolution Time')
    ax2.set_ylabel('Avg. Resolution Time (Days)', color=color_resolution)
    ax2.tick_params(axis='y', labelcolor=color_resolution)

    # Combine legends
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')

    plt.title(f'Monthly Bug Metrics: Reported vs Closed (since {cutoff_date.strftime("%b %Y")})', 
              fontsize=14, fontweight='bold')
    plt.grid(True, which='both', linestyle='--', linewidth=0.5, alpha=0.7)
    fig.tight_layout()

    plt.savefig(output_filename, dpi=300, bbox_inches='tight')
    print(f"Chart saved as {output_filename}")

def generate_detailed_monthly_report(monthly_bugs, metrics, output_filename, cutoff_date):
    """
    Generates an enhanced markdown report with additional statistics.
    """
    if not monthly_bugs:
        print("No bugs to write to markdown report.")
        return
        
    report_lines = [
        f"# Monthly Bug Report (since {cutoff_date.strftime('%B %Y')})\n",
        "## Summary Statistics\n"
    ]

    # Calculate overall statistics
    total_reported = sum(data['reported_count'] for data in metrics.values())
    total_closed = sum(data['closed_count'] for data in metrics.values())
    
    # Calculate average resolution time across all months
    all_resolution_times = []
    for data in metrics.values():
        if data['avg_resolution_days'] > 0:
            all_resolution_times.append(data['avg_resolution_days'])
    
    overall_avg_resolution = sum(all_resolution_times) / len(all_resolution_times) if all_resolution_times else 0

    report_lines.extend([
        f"- **Total Bugs Reported**: {total_reported}",
        f"- **Total Bugs Closed**: {total_closed}",
        f"- **Open Bug Rate**: {((total_reported - total_closed) / total_reported * 100):.1f}% ({total_reported - total_closed} open bugs)" if total_reported > 0 else "- **Open Bug Rate**: 0%",
        f"- **Overall Average Resolution Time**: {overall_avg_resolution:.1f} days\n",
        "## Monthly Breakdown\n"
    ])

    for month, issues in sorted(monthly_bugs.items()):
        month_metrics = metrics.get(month, {})
        closed_count = month_metrics.get('closed_count', 0)
        avg_resolution = month_metrics.get('avg_resolution_days', 0)
        
        report_lines.append(f"### {month}")
        report_lines.append(f"- **Reported**: {len(issues)} bugs")
        report_lines.append(f"- **Closed**: {closed_count} bugs")
        if avg_resolution > 0:
            report_lines.append(f"- **Average Resolution Time**: {avg_resolution:.1f} days")
        report_lines.append("")
        
        for issue in issues:
            assignees = [a['login'] for a in issue.get("assignees", {}).get("nodes", [])] or ["Unassigned"]
            details = f"- **#{issue['number']} {issue['title']}** ([Link]({issue['url']}))"
            details += f"\n  - **Assignees**: {', '.join(assignees)}"
            if issue.get('closedAt'):
                created_at = datetime.fromisoformat(issue['createdAt'].replace('Z', '+00:00'))
                closed_at = datetime.fromisoformat(issue['closedAt'].replace('Z', '+00:00'))
                resolution_time = closed_at - created_at
                days = resolution_time.days
                hours, rem = divmod(resolution_time.seconds, 3600)
                mins, _ = divmod(rem, 60)
                details += f"\n  - **Status**: ✅ Closed (Resolved in: {days}d {hours}h {mins}m)"
            else:
                details += f"\n  - **Status**: 🔴 Open"
            report_lines.append(details)
        report_lines.append("")

    with open(output_filename, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    print(f"Enhanced markdown report saved as {output_filename}")


def main():
    parser = argparse.ArgumentParser(description="Fetch GitHub project issues and generate a bug metrics report and chart.")
    parser.add_argument("--org", help="GitHub organization name.")
    parser.add_argument("--user", help="GitHub user name (for user-owned projects).")
    parser.add_argument("--project", type=int, required=True, help="GitHub project number.")
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"), help="GitHub personal access token (default: from environment variable GITHUB_TOKEN)")
    parser.add_argument("--chart-output", default="bug_metrics_chart.png", help="Output chart file name (default: bug_metrics_chart.png)")
    parser.add_argument("--md-output", default="bug_report.md", help="Output markdown report file name (default: bug_report.md)")
    parser.add_argument("--cutoff-date", default="01/10/2024", help="Cut off date of the earliest issues to use provided in the format DD/MM/YYYY. (default: 01/10/2024)")
    parser.add_argument("--limit-repositories", action='store_true', help="Only use issues from the REPOSITORIES constant list.")
    args = parser.parse_args()
    
    if not args.token:
        print("Error: GitHub token is required. Set it using --token or the GITHUB_TOKEN environment variable.")
        return
        
    if not args.org and not args.user:
        print("Error: You must provide either an organization (--org) or a user (--user).")
        return
        
    if args.org and args.user:
        print("Error: Please provide either --org or --user, not both.")
        return

    items = fetch_all_github_project_items(token=args.token, project_number=args.project, org=args.org, user=args.user)
    
    if items is None:
        print("Could not fetch project items. Exiting.")
        return
    
    # Filtering logic for repositories
    if args.limit_repositories:
        print(f"\nFiltering issues to only include repositories: {REPOSITORIES}")
        original_count = len(items)
        items = [
            item for item in items
            if (content := item.get("content")) and content.get("__typename") == "Issue" and
               (repo := content.get("repository")) and repo.get("name") in REPOSITORIES
        ]
        print(f"Filtered down from {original_count} to {len(items)} issues.")

    # Fixed bug: parse cutoff_date from args before using it
    cutoff_date = datetime.strptime(args.cutoff_date, "%d/%m/%Y").replace(tzinfo=timezone.utc)
    
    monthly_bug_metrics, monthly_bugs_raw = analyze_bugs_by_month(items, cutoff_date)
    
    print(f"\n--- Monthly Bug Metrics (since {cutoff_date.strftime('%B %Y')}) ---")
    if monthly_bug_metrics:
        for month, data in monthly_bug_metrics.items():
            print(f"{month}: {data['reported_count']} reported, {data['closed_count']} closed, Avg. Resolution: {data['avg_resolution_days']:.2f} days")
    else:
        print("No bug data found to analyze for the specified period.")
    print("--------------------------------------------------\n")

    generate_chart(monthly_bug_metrics, args.chart_output, cutoff_date)
    generate_detailed_monthly_report(monthly_bugs_raw, monthly_bug_metrics, args.md_output, cutoff_date)

if __name__ == "__main__":
    main()
