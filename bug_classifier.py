import re
from typing import Dict, List, Tuple

class GitHubBugClassifier:
    def __init__(self):
        # Bug-indicating keywords with different weights
        self.bug_keywords = {
            'high': ['bug', 'error', 'crash', 'broken', 'fail', 'exception', 'traceback', 'stacktrace'],
            'medium': ['issue', 'problem', 'incorrect', 'wrong', 'unexpected', 'defect', 'regression'],
            'low': ['fix', 'resolve', 'solve', 'not working', "doesn't work", 'malfunction']
        }
        
        # Template/structure patterns
        self.bug_patterns = [
            r'steps to reproduce',
            r'expected behavior',
            r'actual behavior',
            r'reproduction steps',
            r'how to reproduce',
            r'version.*?:',
            r'os.*?:',
            r'browser.*?:',
            r'environment.*?:',
            r'stack trace',
            r'error message',
            r'console.*?error',
            r'uncaught.*?exception',
            r'null pointer',
            r'segmentation fault',
            r'memory leak'
        ]
        
        # Bug report prefixes/suffixes
        self.bug_indicators = [
            r'^\[bug\]',
            r'^\[error\]',
            r'^\[issue\]',
            r'^bug:',
            r'^error:',
            r'^fix:',
            r'#\d+.*?error',
            r'#\d+.*?bug',
            r'throws.*?exception',
            r'returns.*?null',
            r'fails.*?to',
            r'crashes.*?when'
        ]
        
        # Non-bug indicators (feature requests, questions, etc.)
        self.non_bug_keywords = [
            'feature request', 'enhancement', 'question', 'documentation', 'proposal',
            'suggestion', 'improvement', 'optimization', 'refactor', 'discussion',
            'help wanted', 'good first issue', 'beginner', 'tutorial'
        ]
        
        # Weights for different categories
        self.weights = {
            'high_keyword': 3,
            'medium_keyword': 2,
            'low_keyword': 1,
            'pattern_match': 2,
            'indicator_match': 3,
            'non_bug_penalty': -2
        }
    
    def preprocess_text(self, text: str) -> str:
        """Clean and normalize text for analysis."""
        if not text:
            return ""
        return text.lower().strip()
    
    def count_keywords(self, text: str) -> Dict[str, int]:
        """Count occurrences of bug-related keywords."""
        text = self.preprocess_text(text)
        counts = {'high': 0, 'medium': 0, 'low': 0}
        
        for category, keywords in self.bug_keywords.items():
            for keyword in keywords:
                counts[category] += text.count(keyword)
        
        return counts
    
    def check_patterns(self, text: str) -> int:
        """Check for bug report patterns and structure."""
        text = self.preprocess_text(text)
        pattern_matches = 0
        
        for pattern in self.bug_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                pattern_matches += 1
        
        return pattern_matches
    
    def check_indicators(self, text: str) -> int:
        """Check for direct bug indicators in title/body."""
        text = self.preprocess_text(text)
        indicator_matches = 0
        
        for indicator in self.bug_indicators:
            if re.search(indicator, text, re.IGNORECASE):
                indicator_matches += 1
        
        return indicator_matches
    
    def check_non_bug_indicators(self, text: str) -> int:
        """Check for non-bug indicators."""
        text = self.preprocess_text(text)
        non_bug_matches = 0
        
        for keyword in self.non_bug_keywords:
            if keyword in text:
                non_bug_matches += 1
        
        return non_bug_matches
    
    def calculate_bug_score(self, title: str, body: str) -> float:
        """Calculate a bug likelihood score for the issue."""
        combined_text = f"{title} {body}"
        
        # Count keywords
        keyword_counts = self.count_keywords(combined_text)
        
        # Check patterns and indicators
        pattern_matches = self.check_patterns(combined_text)
        indicator_matches = self.check_indicators(combined_text)
        non_bug_matches = self.check_non_bug_indicators(combined_text)
        
        # Calculate weighted score
        score = (
            keyword_counts['high'] * self.weights['high_keyword'] +
            keyword_counts['medium'] * self.weights['medium_keyword'] +
            keyword_counts['low'] * self.weights['low_keyword'] +
            pattern_matches * self.weights['pattern_match'] +
            indicator_matches * self.weights['indicator_match'] +
            non_bug_matches * self.weights['non_bug_penalty']
        )
        
        return score
    
    def classify_issue(self, title: str, body: str, threshold: float = 3.0) -> Dict:
        """Classify an issue as bug or not bug with confidence score."""
        score = self.calculate_bug_score(title, body)
        is_bug = score >= threshold
        
        # Calculate confidence (normalized score)
        confidence = min(abs(score) / 10.0, 1.0)
        
        return {
            'is_bug': is_bug,
            'score': score,
            'confidence': confidence,
            'classification': 'bug' if is_bug else 'not_bug'
        }
    
    def check_labels(self, issue: Dict) -> Tuple[bool, int]:
        """Check if labels indicate this is a bug (highest priority signal)."""
        labels = issue.get("labels", {}).get("nodes", [])
        bug_label_found = False
        label_score = 0
        
        bug_label_keywords = ['bug', 'defect', 'error', 'issue', 'critical', 'urgent', 'fix']
        non_bug_labels = ['enhancement', 'feature', 'question', 'documentation', 'help wanted']
        
        for label in labels:
            label_name = label.get('name', '').lower()
            
            # Strong bug indicators
            if any(keyword in label_name for keyword in bug_label_keywords):
                bug_label_found = True
                label_score += 5
            
            # Non-bug indicators
            elif any(keyword in label_name for keyword in non_bug_labels):
                label_score -= 3
        
        return bug_label_found, label_score
    
    def classify_single_issue(self, issue, threshold: float = 3.0) -> Dict:
        """Classify a single issue using GitHub issue structure."""
        # Extract title and body
        title = issue.get('title', '') or ''
        body = issue.get('body', '') or ''
        
        # Check labels first (most reliable signal)
        has_bug_label, label_score = self.check_labels(issue)
        
        # If there's a clear bug label, return early with high confidence
        if has_bug_label and label_score >= 5:
            return {
                'title': title,
                'body': body,
                'is_bug': True,
                'score': label_score,
                'confidence': 0.9,
                'classification': 'bug',
                'reason': 'bug_label_found'
            }
        
        # Otherwise, use content-based classification
        content_score = self.calculate_bug_score(title, body)
        final_score = content_score + label_score
        
        is_bug = final_score >= threshold
        confidence = min(abs(final_score) / 10.0, 1.0)
        
        return {
            'title': title,
            'body': body,
            'is_bug': is_bug,
            'score': final_score,
            'content_score': content_score,
            'label_score': label_score,
            'confidence': confidence,
            'classification': 'bug' if is_bug else 'not_bug',
            'reason': 'label_and_content' if label_score != 0 else 'content_only'
        }
    
    def classify_issues(self, issues: List[Dict], threshold: float = 3.0) -> List[Dict]:
        """Classify multiple issues."""
        results = []
        
        for issue in issues:
            result = self.classify_single_issue(issue, threshold)
            results.append(result)
        
        return results
    
    def get_bug_statistics(self, results: List[Dict]) -> Dict:
        """Get statistics about bug classification."""
        total_issues = len(results)
        bug_count = sum(1 for r in results if r['is_bug'])
        
        avg_bug_score = sum(r['score'] for r in results if r['is_bug']) / max(bug_count, 1)
        avg_non_bug_score = sum(r['score'] for r in results if not r['is_bug']) / max(total_issues - bug_count, 1)
        
        return {
            'total_issues': total_issues,
            'bug_count': bug_count,
            'non_bug_count': total_issues - bug_count,
            'bug_percentage': (bug_count / total_issues) * 100,
            'avg_bug_score': avg_bug_score,
            'avg_non_bug_score': avg_non_bug_score
        }

