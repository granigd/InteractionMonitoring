"""
Friction detection algorithms for GLSP interaction analysis.

Detects user friction patterns including:
- Rage clicks (rapid frustrated clicking)
- Undo/redo bursts (excessive corrections)
- Navigation thrashing (erratic viewport movement)
- Rapid deletions (mass delete indicating frustration)

These patterns indicate usability issues or user confusion.
"""

import math
from typing import List, Optional, Tuple, Dict, Any
from collections import defaultdict

from analysis.schema import (
    FrictionAnalysisConfig,
    FrictionType,
    FrictionSeverity,
    RageClickEvent,
    UndoRedoBurst,
    NavigationThrashEvent,
    RapidDeletionEvent,
    FrictionIndicator,
    RageClickSummary,
    UndoRedoSummary,
    NavigationThrashSummary,
    RapidDeletionSummary,
    FrictionScore,
)


def calculate_distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """Calculate Euclidean distance between two points"""
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


def calculate_centroid(points: List[Tuple[float, float]]) -> Tuple[float, float]:
    """Calculate centroid of a set of points"""
    if not points:
        return (0.0, 0.0)
    x_sum = sum(p[0] for p in points)
    y_sum = sum(p[1] for p in points)
    n = len(points)
    return (x_sum / n, y_sum / n)


def calculate_radius(points: List[Tuple[float, float]], centroid: Tuple[float, float]) -> float:
    """Calculate maximum radius from centroid to any point"""
    if not points:
        return 0.0
    return max(calculate_distance(centroid[0], centroid[1], p[0], p[1]) for p in points)


def get_severity_for_count(count: int, thresholds: Tuple[int, int, int]) -> FrictionSeverity:
    """Determine severity based on count and thresholds (low, medium, high)"""
    low, medium, high = thresholds
    if count >= high:
        return FrictionSeverity.CRITICAL
    elif count >= medium:
        return FrictionSeverity.HIGH
    elif count >= low:
        return FrictionSeverity.MEDIUM
    return FrictionSeverity.LOW


class FrictionDetector:
    """
    Detects user friction patterns in GLSP interaction sessions.
    
    Analyzes event sequences to identify rage clicks, undo/redo bursts,
    navigation thrashing, and rapid deletions that indicate usability issues.
    """
    
    def __init__(self, config: Optional[FrictionAnalysisConfig] = None):
        self.config = config or FrictionAnalysisConfig()
        
        # Event type mappings
        self.click_event_types = {'mouse_click', 'element_select'}
        self.click_event_kinds = {'elementSelected'}
        self.undo_event_kinds = {'undo', 'UndoAction'}
        self.redo_event_kinds = {'redo', 'RedoAction'}
        self.navigation_event_kinds = {'setViewport', 'center', 'fit', 'scroll', 'zoom'}
        self.navigation_event_types = {'viewport_change', 'scroll', 'zoom_change'}
        self.deletion_event_kinds = {'deleteElement', 'delete'}
        self.deletion_event_types = {'element_delete'}
    
    def detect_rage_clicks(self, events: List[Dict[str, Any]]) -> RageClickSummary:
        """
        Detect rage click patterns - rapid clicking in frustration.
        
        Criteria:
        - Multiple clicks (>= min_clicks) within time window
        - Clicks are spatially close (within max_radius)
        """
        click_events = []
        
        # Extract click events with positions
        for i, event in enumerate(events):
            event_type = event.get('event_type', '')
            event_kind = event.get('event_kind', '')
            
            is_click = (
                event_type in self.click_event_types or
                event_kind in self.click_event_kinds or
                event_type == 'mouse_click'
            )
            
            if is_click and event.get('position_x') is not None:
                click_events.append({
                    'index': i,
                    'seq': event.get('sequence_number', i),
                    'timestamp': event.get('timestamp'),
                    'x': event.get('position_x'),
                    'y': event.get('position_y'),
                    'element_id': event.get('element_id'),
                    'element_type': event.get('element_type'),
                })
        
        rage_click_events = []
        used_indices = set()
        
        # Sliding window detection
        for i, click in enumerate(click_events):
            if i in used_indices:
                continue
            
            cluster = [click]
            cluster_indices = {i}
            
            # Find clicks within time window
            for j in range(i + 1, len(click_events)):
                if j in used_indices:
                    continue
                
                other = click_events[j]
                time_diff = (other['timestamp'] - click['timestamp']).total_seconds() * 1000
                
                if time_diff > self.config.rage_click_time_window_ms:
                    break
                
                # Check spatial proximity to cluster centroid
                points = [(c['x'], c['y']) for c in cluster]
                centroid = calculate_centroid(points)
                distance = calculate_distance(centroid[0], centroid[1], other['x'], other['y'])
                
                if distance <= self.config.rage_click_max_radius_px:
                    cluster.append(other)
                    cluster_indices.add(j)
            
            # Check if this is a rage click cluster
            if len(cluster) >= self.config.rage_click_min_clicks:
                used_indices.update(cluster_indices)
                
                points = [(c['x'], c['y']) for c in cluster]
                centroid = calculate_centroid(points)
                radius = calculate_radius(points, centroid)
                
                start_time = cluster[0]['timestamp']
                end_time = cluster[-1]['timestamp']
                duration_ms = int((end_time - start_time).total_seconds() * 1000)
                
                # Determine most common element
                element_ids = [c['element_id'] for c in cluster if c['element_id']]
                element_types = [c['element_type'] for c in cluster if c['element_type']]
                
                rage_event = RageClickEvent(
                    start_time=start_time,
                    end_time=end_time,
                    click_count=len(cluster),
                    duration_ms=duration_ms,
                    position_x=centroid[0],
                    position_y=centroid[1],
                    radius_px=radius,
                    element_id=element_ids[0] if element_ids else None,
                    element_type=element_types[0] if element_types else None,
                    severity=get_severity_for_count(len(cluster), (3, 5, 8)),
                    click_sequence_numbers=[c['seq'] for c in cluster],
                )
                rage_click_events.append(rage_event)
        
        # Calculate summary statistics
        total_rage_clicks = sum(e.click_count for e in rage_click_events)
        affected_elements = len(set(e.element_id for e in rage_click_events if e.element_id))
        
        # Find hotspot positions
        hotspots = []
        if rage_click_events:
            position_counts = defaultdict(int)
            for e in rage_click_events:
                if e.position_x and e.position_y:
                    # Round to grid for clustering
                    grid_x = round(e.position_x / 50) * 50
                    grid_y = round(e.position_y / 50) * 50
                    position_counts[(grid_x, grid_y)] += e.click_count
            
            # Get top 5 hotspots
            sorted_positions = sorted(position_counts.items(), key=lambda x: x[1], reverse=True)[:5]
            hotspots = [
                {'x': pos[0], 'y': pos[1], 'count': count}
                for pos, count in sorted_positions
            ]
        
        return RageClickSummary(
            total_events=len(rage_click_events),
            events=rage_click_events,
            affected_elements=affected_elements,
            total_rage_clicks=total_rage_clicks,
            avg_clicks_per_event=total_rage_clicks / len(rage_click_events) if rage_click_events else 0,
            max_clicks_in_event=max((e.click_count for e in rage_click_events), default=0),
            hotspot_positions=hotspots,
        )
    
    def detect_undo_redo_bursts(self, events: List[Dict[str, Any]]) -> UndoRedoSummary:
        """
        Detect undo/redo burst patterns - excessive corrections indicating confusion.
        
        Criteria:
        - Multiple undo/redo operations within time window
        - Looking for patterns like UUURRRUUU (back and forth)
        """
        undo_redo_events = []
        
        # Extract undo/redo events
        for i, event in enumerate(events):
            event_type = event.get('event_type', '')
            event_kind = event.get('event_kind', '')
            data = event.get('data', {})
            
            # Check for undo
            is_undo = (
                event_kind in self.undo_event_kinds or
                data.get('kind') in self.undo_event_kinds or
                'undo' in event_type.lower()
            )
            
            # Check for redo
            is_redo = (
                event_kind in self.redo_event_kinds or
                data.get('kind') in self.redo_event_kinds or
                'redo' in event_type.lower()
            )
            
            if is_undo or is_redo:
                undo_redo_events.append({
                    'index': i,
                    'seq': event.get('sequence_number', i),
                    'timestamp': event.get('timestamp'),
                    'type': 'undo' if is_undo else 'redo',
                })
        
        bursts = []
        used_indices = set()
        
        # Sliding window detection
        for i, ur_event in enumerate(undo_redo_events):
            if i in used_indices:
                continue
            
            cluster = [ur_event]
            cluster_indices = {i}
            
            # Find operations within time window
            for j in range(i + 1, len(undo_redo_events)):
                if j in used_indices:
                    continue
                
                other = undo_redo_events[j]
                time_diff = (other['timestamp'] - ur_event['timestamp']).total_seconds() * 1000
                
                if time_diff > self.config.undo_redo_time_window_ms:
                    break
                
                cluster.append(other)
                cluster_indices.add(j)
            
            # Check if this is a burst
            if len(cluster) >= self.config.undo_redo_min_operations:
                used_indices.update(cluster_indices)
                
                undo_count = sum(1 for c in cluster if c['type'] == 'undo')
                redo_count = sum(1 for c in cluster if c['type'] == 'redo')
                
                start_time = cluster[0]['timestamp']
                end_time = cluster[-1]['timestamp']
                duration_ms = int((end_time - start_time).total_seconds() * 1000)
                
                # Create pattern string
                pattern = ''.join('U' if c['type'] == 'undo' else 'R' for c in cluster)
                
                # Higher severity for back-and-forth patterns
                has_oscillation = 'UR' in pattern or 'RU' in pattern
                severity_count = len(cluster)
                if has_oscillation:
                    severity_count += 2
                
                burst = UndoRedoBurst(
                    start_time=start_time,
                    end_time=end_time,
                    undo_count=undo_count,
                    redo_count=redo_count,
                    total_operations=len(cluster),
                    duration_ms=duration_ms,
                    net_effect=undo_count - redo_count,
                    severity=get_severity_for_count(severity_count, (3, 5, 8)),
                    sequence_numbers=[c['seq'] for c in cluster],
                    pattern=pattern,
                )
                bursts.append(burst)
        
        # Calculate summary
        total_undos = sum(b.undo_count for b in bursts)
        total_redos = sum(b.redo_count for b in bursts)
        time_spent = sum(b.duration_ms for b in bursts)
        
        # Find common patterns
        pattern_counts = defaultdict(int)
        for b in bursts:
            # Normalize pattern to a template
            normalized = b.pattern[:10]  # Truncate long patterns
            pattern_counts[normalized] += 1
        
        common_patterns = [
            {'pattern': p, 'count': c, 'interpretation': self._interpret_pattern(p)}
            for p, c in sorted(pattern_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        ]
        
        return UndoRedoSummary(
            total_bursts=len(bursts),
            bursts=bursts,
            total_undos=total_undos,
            total_redos=total_redos,
            avg_burst_size=sum(b.total_operations for b in bursts) / len(bursts) if bursts else 0,
            max_burst_size=max((b.total_operations for b in bursts), default=0),
            time_spent_undoing_ms=time_spent,
            common_patterns=common_patterns,
        )
    
    def _interpret_pattern(self, pattern: str) -> str:
        """Interpret an undo/redo pattern"""
        if pattern.count('U') > 0 and pattern.count('R') == 0:
            return "Pure undo sequence - reverting multiple changes"
        elif pattern.count('R') > 0 and pattern.count('U') == 0:
            return "Pure redo sequence - reapplying changes"
        elif 'URUR' in pattern or 'RURU' in pattern:
            return "Oscillating pattern - user uncertain about action"
        elif pattern.startswith('UU') and pattern.endswith('RR'):
            return "Over-undo then recover pattern"
        else:
            return "Mixed undo/redo activity"
    
    def detect_navigation_thrash(self, events: List[Dict[str, Any]]) -> NavigationThrashSummary:
        """
        Detect navigation thrashing - erratic viewport/zoom changes.
        
        Criteria:
        - Multiple viewport/zoom changes within time window
        - Indicates user having trouble locating or viewing content
        """
        nav_events = []
        
        # Extract navigation events
        for i, event in enumerate(events):
            event_type = event.get('event_type', '')
            event_kind = event.get('event_kind', '')
            data = event.get('data', {})
            
            is_nav = (
                event_type in self.navigation_event_types or
                event_kind in self.navigation_event_kinds or
                data.get('kind') in self.navigation_event_kinds
            )
            
            if is_nav:
                # Try to extract position
                pos_x = event.get('position_x')
                pos_y = event.get('position_y')
                
                if pos_x is None:
                    scroll = data.get('scroll', {})
                    pos_x = scroll.get('x')
                    pos_y = scroll.get('y')
                
                nav_events.append({
                    'index': i,
                    'seq': event.get('sequence_number', i),
                    'timestamp': event.get('timestamp'),
                    'type': event_kind or event_type,
                    'x': pos_x,
                    'y': pos_y,
                })
        
        thrash_events = []
        used_indices = set()
        
        # Sliding window detection
        for i, nav_event in enumerate(nav_events):
            if i in used_indices:
                continue
            
            cluster = [nav_event]
            cluster_indices = {i}
            
            for j in range(i + 1, len(nav_events)):
                if j in used_indices:
                    continue
                
                other = nav_events[j]
                time_diff = (other['timestamp'] - nav_event['timestamp']).total_seconds() * 1000
                
                if time_diff > self.config.nav_time_window_ms:
                    break
                
                cluster.append(other)
                cluster_indices.add(j)
            
            if len(cluster) >= self.config.nav_min_changes:
                used_indices.update(cluster_indices)
                
                # Count different types
                viewport_changes = sum(1 for c in cluster if c['type'] in {'setViewport', 'viewport_change'})
                zoom_changes = sum(1 for c in cluster if c['type'] in {'zoom', 'fit', 'center', 'zoom_change'})
                scroll_events = sum(1 for c in cluster if c['type'] == 'scroll')
                
                start_time = cluster[0]['timestamp']
                end_time = cluster[-1]['timestamp']
                duration_ms = int((end_time - start_time).total_seconds() * 1000)
                
                # Calculate distance traveled
                distance = 0.0
                for k in range(1, len(cluster)):
                    prev = cluster[k-1]
                    curr = cluster[k]
                    if prev['x'] is not None and curr['x'] is not None:
                        distance += calculate_distance(prev['x'], prev['y'], curr['x'], curr['y'])
                
                thrash_event = NavigationThrashEvent(
                    start_time=start_time,
                    end_time=end_time,
                    viewport_changes=viewport_changes,
                    zoom_changes=zoom_changes,
                    scroll_events=scroll_events,
                    total_changes=len(cluster),
                    duration_ms=duration_ms,
                    distance_traveled_px=distance if distance > 0 else None,
                    severity=get_severity_for_count(len(cluster), (5, 8, 12)),
                    sequence_numbers=[c['seq'] for c in cluster],
                )
                thrash_events.append(thrash_event)
        
        return NavigationThrashSummary(
            total_events=len(thrash_events),
            events=thrash_events,
            total_viewport_changes=sum(e.viewport_changes for e in thrash_events),
            total_zoom_changes=sum(e.zoom_changes for e in thrash_events),
            avg_changes_per_event=sum(e.total_changes for e in thrash_events) / len(thrash_events) if thrash_events else 0,
            total_distance_traveled_px=sum(e.distance_traveled_px or 0 for e in thrash_events) or None,
        )
    
    def detect_rapid_deletions(self, events: List[Dict[str, Any]]) -> RapidDeletionSummary:
        """
        Detect rapid deletion patterns - mass deletes indicating frustration.
        
        Criteria:
        - Multiple deletions within time window
        - Indicates user abandoning or restarting work
        """
        deletion_events = []
        
        for i, event in enumerate(events):
            event_type = event.get('event_type', '')
            event_kind = event.get('event_kind', '')
            data = event.get('data', {})
            
            is_deletion = (
                event_type in self.deletion_event_types or
                event_kind in self.deletion_event_kinds or
                data.get('kind') in self.deletion_event_kinds
            )
            
            if is_deletion:
                deletion_events.append({
                    'index': i,
                    'seq': event.get('sequence_number', i),
                    'timestamp': event.get('timestamp'),
                    'element_type': event.get('element_type'),
                })
        
        rapid_deletions = []
        used_indices = set()
        
        for i, del_event in enumerate(deletion_events):
            if i in used_indices:
                continue
            
            cluster = [del_event]
            cluster_indices = {i}
            
            for j in range(i + 1, len(deletion_events)):
                if j in used_indices:
                    continue
                
                other = deletion_events[j]
                time_diff = (other['timestamp'] - del_event['timestamp']).total_seconds() * 1000
                
                if time_diff > self.config.deletion_time_window_ms:
                    break
                
                cluster.append(other)
                cluster_indices.add(j)
            
            if len(cluster) >= self.config.deletion_min_count:
                used_indices.update(cluster_indices)
                
                start_time = cluster[0]['timestamp']
                end_time = cluster[-1]['timestamp']
                duration_ms = int((end_time - start_time).total_seconds() * 1000)
                
                element_types = [c['element_type'] for c in cluster if c['element_type']]
                
                rapid_del = RapidDeletionEvent(
                    start_time=start_time,
                    end_time=end_time,
                    deletion_count=len(cluster),
                    duration_ms=duration_ms,
                    deleted_element_types=element_types,
                    severity=get_severity_for_count(len(cluster), (3, 5, 8)),
                    sequence_numbers=[c['seq'] for c in cluster],
                )
                rapid_deletions.append(rapid_del)
        
        # Find most deleted types
        type_counts = defaultdict(int)
        for rd in rapid_deletions:
            for et in rd.deleted_element_types:
                type_counts[et] += 1
        
        most_deleted = [
            {'type': t, 'count': c}
            for t, c in sorted(type_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        ]
        
        return RapidDeletionSummary(
            total_events=len(rapid_deletions),
            events=rapid_deletions,
            total_deletions=sum(rd.deletion_count for rd in rapid_deletions),
            most_deleted_types=most_deleted,
        )
    
    def calculate_friction_score(
        self,
        rage_clicks: RageClickSummary,
        undo_redo: UndoRedoSummary,
        navigation: NavigationThrashSummary,
        deletions: RapidDeletionSummary,
        total_events: int,
        session_duration_ms: Optional[int] = None,
    ) -> FrictionScore:
        """
        Calculate overall friction score from all detected patterns.
        
        Score is 0-100 where:
        - 0-20: Minimal friction (normal usage)
        - 21-40: Low friction (some minor issues)
        - 41-60: Moderate friction (notable usability concerns)
        - 61-80: High friction (significant user struggle)
        - 81-100: Critical friction (severe usability problems)
        """
        # Base scores from event counts
        rage_score = min(100, rage_clicks.total_events * 15 + rage_clicks.total_rage_clicks * 3)
        undo_score = min(100, undo_redo.total_bursts * 12 + undo_redo.total_undos * 2)
        nav_score = min(100, navigation.total_events * 10 + navigation.total_viewport_changes * 2)
        deletion_score = min(100, deletions.total_events * 15 + deletions.total_deletions * 4)
        
        # Adjust for severity
        for event in rage_clicks.events:
            if event.severity == FrictionSeverity.CRITICAL:
                rage_score = min(100, rage_score + 10)
            elif event.severity == FrictionSeverity.HIGH:
                rage_score = min(100, rage_score + 5)
        
        for burst in undo_redo.bursts:
            if burst.severity == FrictionSeverity.CRITICAL:
                undo_score = min(100, undo_score + 10)
            elif burst.severity == FrictionSeverity.HIGH:
                undo_score = min(100, undo_score + 5)
        
        # Normalize by session length/event count
        if total_events > 0:
            friction_event_count = (
                rage_clicks.total_rage_clicks +
                undo_redo.total_undos + undo_redo.total_redos +
                navigation.total_viewport_changes + navigation.total_zoom_changes +
                deletions.total_deletions
            )
            friction_ratio = friction_event_count / total_events
            
            # If friction is a high proportion of events, increase scores
            if friction_ratio > 0.3:
                multiplier = 1 + (friction_ratio - 0.3)
                rage_score = min(100, rage_score * multiplier)
                undo_score = min(100, undo_score * multiplier)
                nav_score = min(100, nav_score * multiplier)
                deletion_score = min(100, deletion_score * multiplier)
        
        # Calculate weighted overall score
        weights = {
            'rage': 0.35,
            'undo_redo': 0.30,
            'navigation': 0.20,
            'deletion': 0.15,
        }
        
        overall = (
            rage_score * weights['rage'] +
            undo_score * weights['undo_redo'] +
            nav_score * weights['navigation'] +
            deletion_score * weights['deletion']
        )
        
        # Generate interpretation
        if overall <= 20:
            interpretation = "Minimal friction detected. User interaction appears smooth and efficient."
        elif overall <= 40:
            interpretation = "Low friction detected. Some minor usability concerns that may warrant attention."
        elif overall <= 60:
            interpretation = "Moderate friction detected. Notable usability issues affecting user experience."
        elif overall <= 80:
            interpretation = "High friction detected. User is experiencing significant difficulties with the interface."
        else:
            interpretation = "Critical friction detected. Severe usability problems requiring immediate attention."
        
        # Generate recommendations
        recommendations = []
        
        if rage_clicks.total_events > 0:
            recommendations.append(
                f"Investigate {rage_clicks.total_events} rage click incident(s). "
                f"Users clicked rapidly {rage_clicks.total_rage_clicks} times, suggesting "
                "unresponsive UI elements or unclear interaction feedback."
            )
            if rage_clicks.hotspot_positions:
                recommendations.append(
                    f"Rage click hotspots detected at positions: {rage_clicks.hotspot_positions[:3]}. "
                    "Consider improving responsiveness or visibility of elements in these areas."
                )
        
        if undo_redo.total_bursts > 0:
            recommendations.append(
                f"Detected {undo_redo.total_bursts} undo/redo burst(s) with {undo_redo.total_undos} undos. "
                "This may indicate unclear action consequences or need for better preview/confirmation dialogs."
            )
            if undo_redo.common_patterns:
                top_pattern = undo_redo.common_patterns[0]
                recommendations.append(
                    f"Most common pattern: {top_pattern['pattern']} - {top_pattern['interpretation']}"
                )
        
        if navigation.total_events > 0:
            recommendations.append(
                f"Detected {navigation.total_events} navigation thrashing incident(s). "
                "Users may be having difficulty locating elements or understanding the diagram layout. "
                "Consider adding a minimap, overview panel, or search functionality."
            )
        
        if deletions.total_events > 0:
            recommendations.append(
                f"Detected {deletions.total_events} rapid deletion incident(s) ({deletions.total_deletions} total deletions). "
                "This may indicate users starting over or experiencing frustration with their work."
            )
        
        if not recommendations:
            recommendations.append("No significant friction patterns detected. Continue monitoring for trends.")
        
        return FrictionScore(
            overall_score=round(overall, 2),
            rage_click_score=round(rage_score, 2),
            undo_redo_score=round(undo_score, 2),
            navigation_score=round(nav_score, 2),
            deletion_score=round(deletion_score, 2),
            interpretation=interpretation,
            recommendations=recommendations,
        )
    
    def analyze_session(self, events: List[Dict[str, Any]], session_duration_ms: Optional[int] = None) -> Dict[str, Any]:
        """
        Perform complete friction analysis on a session's events.
        
        Returns all detection results and calculated scores.
        """
        # Run all detectors
        rage_clicks = self.detect_rage_clicks(events)
        undo_redo = self.detect_undo_redo_bursts(events)
        navigation = self.detect_navigation_thrash(events)
        deletions = self.detect_rapid_deletions(events)
        
        # Calculate overall score
        friction_score = self.calculate_friction_score(
            rage_clicks=rage_clicks,
            undo_redo=undo_redo,
            navigation=navigation,
            deletions=deletions,
            total_events=len(events),
            session_duration_ms=session_duration_ms,
        )
        
        # Collect all friction indicators chronologically
        all_indicators = []
        
        for event in rage_clicks.events:
            all_indicators.append(FrictionIndicator(
                type=FrictionType.RAGE_CLICK,
                severity=event.severity,
                timestamp=event.start_time,
                duration_ms=event.duration_ms,
                description=f"Rage click: {event.click_count} rapid clicks",
                details={
                    'click_count': event.click_count,
                    'position': {'x': event.position_x, 'y': event.position_y},
                    'element_id': event.element_id,
                },
                sequence_start=event.click_sequence_numbers[0] if event.click_sequence_numbers else 0,
                sequence_end=event.click_sequence_numbers[-1] if event.click_sequence_numbers else 0,
            ))
        
        for burst in undo_redo.bursts:
            all_indicators.append(FrictionIndicator(
                type=FrictionType.UNDO_REDO_BURST,
                severity=burst.severity,
                timestamp=burst.start_time,
                duration_ms=burst.duration_ms,
                description=f"Undo/redo burst: {burst.undo_count} undos, {burst.redo_count} redos",
                details={
                    'undo_count': burst.undo_count,
                    'redo_count': burst.redo_count,
                    'pattern': burst.pattern,
                },
                sequence_start=burst.sequence_numbers[0] if burst.sequence_numbers else 0,
                sequence_end=burst.sequence_numbers[-1] if burst.sequence_numbers else 0,
            ))
        
        for event in navigation.events:
            all_indicators.append(FrictionIndicator(
                type=FrictionType.NAVIGATION_THRASH,
                severity=event.severity,
                timestamp=event.start_time,
                duration_ms=event.duration_ms,
                description=f"Navigation thrash: {event.total_changes} viewport changes",
                details={
                    'viewport_changes': event.viewport_changes,
                    'zoom_changes': event.zoom_changes,
                    'scroll_events': event.scroll_events,
                },
                sequence_start=event.sequence_numbers[0] if event.sequence_numbers else 0,
                sequence_end=event.sequence_numbers[-1] if event.sequence_numbers else 0,
            ))
        
        for event in deletions.events:
            all_indicators.append(FrictionIndicator(
                type=FrictionType.RAPID_ELEMENT_DELETION,
                severity=event.severity,
                timestamp=event.start_time,
                duration_ms=event.duration_ms,
                description=f"Rapid deletion: {event.deletion_count} elements deleted",
                details={
                    'deletion_count': event.deletion_count,
                    'element_types': event.deleted_element_types,
                },
                sequence_start=event.sequence_numbers[0] if event.sequence_numbers else 0,
                sequence_end=event.sequence_numbers[-1] if event.sequence_numbers else 0,
            ))
        
        # Sort by timestamp
        all_indicators.sort(key=lambda x: x.timestamp)
        
        # Calculate friction event count
        events_with_friction = (
            rage_clicks.total_rage_clicks +
            sum(b.total_operations for b in undo_redo.bursts) +
            sum(e.total_changes for e in navigation.events) +
            sum(e.deletion_count for e in deletions.events)
        )
        
        return {
            'friction_score': friction_score,
            'rage_clicks': rage_clicks,
            'undo_redo': undo_redo,
            'navigation_thrash': navigation,
            'rapid_deletions': deletions,
            'all_indicators': all_indicators,
            'events_with_friction': events_with_friction,
            'friction_percentage': round((events_with_friction / len(events)) * 100, 2) if events else 0,
        }
