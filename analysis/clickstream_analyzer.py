"""
Clickstream analysis for GLSP interaction sessions.

Provides:
- N-gram analysis (bigrams, trigrams)
- Transition frequency analysis
- XES export for process mining
"""

from collections import Counter
from datetime import datetime
from typing import List, Dict, Any, Optional
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom


class ClickstreamAnalyzer:
    """Analyzes event sequences to extract behavioral patterns."""
    
    # Events to exclude from clickstream (low-level noise)
    EXCLUDED_EVENTS = {'mouse_click', 'element_select'}
    
    def __init__(self, granularity: str = 'full'):
        """
        Args:
            granularity: Level of detail for event labels
                - 'type': event_type only (e.g., 'element_create')
                - 'kind': event_type + event_kind (e.g., 'element_create:createNode')
                - 'full': event_type + event_kind + element_type 
                          (e.g., 'element_create:createNode:CLASS__Property')
        """
        self.granularity = granularity
    
    def _clean_element_type(self, element_type: str) -> str:
        """Remove namespace prefixes like CLASS__, ACTIVITY__, etc."""
        if '__' in element_type:
            return element_type.split('__', 1)[1]
        return element_type
    
    def _get_event_label(self, event: dict) -> str:
        """Build event label based on granularity setting."""
        event_type = event.get('event_type', 'UNKNOWN')
        
        if self.granularity == 'type':
            return event_type
        
        event_kind = event.get('event_kind') or ''
        
        if self.granularity == 'kind':
            if event_kind:
                return f"{event_type}:{event_kind}"
            return event_type
        
        # granularity == 'full'
        element_type = event.get('element_type') or ''
        if element_type:
            element_type = self._clean_element_type(element_type)
        
        parts = [event_type]
        if event_kind:
            parts.append(event_kind)
        if element_type:
            parts.append(element_type)
        return ':'.join(parts)
    
    def _should_include(self, event: dict) -> bool:
        """Check if event should be included in clickstream."""
        event_type = event.get('event_type', '')
        event_kind = event.get('event_kind', '')
        return event_type not in self.EXCLUDED_EVENTS and event_kind not in self.EXCLUDED_EVENTS
    
    def extract_sequence(self, events: List[dict]) -> List[str]:
        """Extract ordered sequence of event labels (excluding noise)."""
        return [self._get_event_label(e) for e in events if self._should_include(e)]
    
    def compute_ngrams(self, sequence: List[str], n: int) -> List[tuple]:
        """Compute n-grams from a sequence."""
        if len(sequence) < n:
            return []
        return [tuple(sequence[i:i+n]) for i in range(len(sequence) - n + 1)]
    
    def analyze_session(
        self, 
        events: List[dict],
        top_k: int = 10
    ) -> Dict[str, Any]:
        """
        Perform clickstream analysis on session events.
        
        Returns:
            Dict with bigrams, trigrams, transitions, and statistics.
        """
        if not events:
            return self._empty_result()
        
        sequence = self.extract_sequence(events)
        
        # Compute n-grams
        bigrams = self.compute_ngrams(sequence, 2)
        trigrams = self.compute_ngrams(sequence, 3)
        
        # Count frequencies
        bigram_counts = Counter(bigrams)
        trigram_counts = Counter(trigrams)
        event_counts = Counter(sequence)
        
        # Build transition matrix (from -> to -> count)
        transitions = {}
        for a, b in bigrams:
            if a not in transitions:
                transitions[a] = {}
            transitions[a][b] = transitions[a].get(b, 0) + 1
        
        return {
            'total_events': len(sequence),  # After filtering
            'total_events_raw': len(events),  # Before filtering
            'unique_event_types': len(event_counts),
            'event_counts': dict(event_counts.most_common()),
            'top_bigrams': [
                {'sequence': list(bg), 'count': c, 'label': ' → '.join(bg)}
                for bg, c in bigram_counts.most_common(top_k)
            ],
            'top_trigrams': [
                {'sequence': list(tg), 'count': c, 'label': ' → '.join(tg)}
                for tg, c in trigram_counts.most_common(top_k)
            ],
            'transitions': transitions,
            'top_transitions': [
                {'from': bg[0], 'to': bg[1], 'count': c}
                for bg, c in bigram_counts.most_common(top_k)
            ],
        }
    
    def _empty_result(self) -> Dict[str, Any]:
        return {
            'total_events': 0,
            'total_events_raw': 0,
            'unique_event_types': 0,
            'event_counts': {},
            'top_bigrams': [],
            'top_trigrams': [],
            'transitions': {},
            'top_transitions': [],
        }


class XESExporter:
    """Export sessions to XES format for process mining tools."""
    
    XES_NAMESPACE = "http://www.xes-standard.org/"
    
    # Events to exclude from XES export
    EXCLUDED_EVENTS = {'mouse_click', 'element_select'}
    
    def _clean_element_type(self, element_type: str) -> str:
        """Remove namespace prefixes like CLASS__, ACTIVITY__, etc."""
        if '__' in element_type:
            return element_type.split('__', 1)[1]
        return element_type
    
    def _should_include(self, event: dict) -> bool:
        """Check if event should be included in export."""
        event_type = event.get('event_type', '')
        event_kind = event.get('event_kind', '')
        return event_type not in self.EXCLUDED_EVENTS and event_kind not in self.EXCLUDED_EVENTS
    
    def export_session(
        self,
        session_id: str,
        events: List[dict],
        session_metadata: Optional[dict] = None
    ) -> str:
        """
        Export a single session as XES XML.
        
        Args:
            session_id: Session identifier
            events: List of event dictionaries
            session_metadata: Optional session-level metadata
            
        Returns:
            XES XML string
        """
        log = Element('log')
        log.set('xes.version', '1.0')
        log.set('xes.features', 'nested-attributes')
        log.set('xmlns', self.XES_NAMESPACE)
        
        # Add extensions
        self._add_extension(log, 'Concept', 'concept', 'http://www.xes-standard.org/concept.xesext')
        self._add_extension(log, 'Time', 'time', 'http://www.xes-standard.org/time.xesext')
        self._add_extension(log, 'Lifecycle', 'lifecycle', 'http://www.xes-standard.org/lifecycle.xesext')
        
        # Add global event attributes
        globals_event = SubElement(log, 'global', scope='event')
        self._add_string_attr(globals_event, 'concept:name', 'UNKNOWN')
        self._add_string_attr(globals_event, 'lifecycle:transition', 'complete')
        
        # Add classifiers
        classifier = SubElement(log, 'classifier')
        classifier.set('name', 'Event Name')
        classifier.set('keys', 'concept:name')
        
        # Create trace (one trace = one session)
        trace = SubElement(log, 'trace')
        self._add_string_attr(trace, 'concept:name', session_id)
        
        # Add session metadata as trace attributes
        if session_metadata:
            if session_metadata.get('tool_id'):
                self._add_string_attr(trace, 'tool:id', session_metadata['tool_id'])
            if session_metadata.get('editor_type'):
                self._add_string_attr(trace, 'editor:type', session_metadata['editor_type'])
            if session_metadata.get('user_name'):
                self._add_string_attr(trace, 'user:name', session_metadata['user_name'])
        
        # Add events (filtered)
        for event_data in events:
            if not self._should_include(event_data):
                continue
                
            event_elem = SubElement(trace, 'event')
            
            # Build full event name: event_type:event_kind:element_type
            event_type = event_data.get('event_type', 'UNKNOWN')
            event_kind = event_data.get('event_kind') or ''
            element_type = event_data.get('element_type') or ''
            if element_type:
                element_type = self._clean_element_type(element_type)
            
            name_parts = [event_type]
            if event_kind:
                name_parts.append(event_kind)
            if element_type:
                name_parts.append(element_type)
            event_name = ':'.join(name_parts)
            
            self._add_string_attr(event_elem, 'concept:name', event_name)
            
            # Timestamp
            ts = event_data.get('timestamp')
            if ts:
                if isinstance(ts, datetime):
                    ts_str = ts.isoformat()
                else:
                    ts_str = str(ts)
                self._add_date_attr(event_elem, 'time:timestamp', ts_str)
            
            # Lifecycle
            self._add_string_attr(event_elem, 'lifecycle:transition', 'complete')
            
            # Additional attributes
            if event_data.get('element_type'):
                self._add_string_attr(event_elem, 'element:type', event_data['element_type'])
            if event_data.get('element_id'):
                self._add_string_attr(event_elem, 'element:id', event_data['element_id'])
            if event_data.get('event_type'):
                self._add_string_attr(event_elem, 'event:type', event_data['event_type'])
        
        # Pretty print
        xml_str = tostring(log, encoding='unicode')
        return minidom.parseString(xml_str).toprettyxml(indent='  ')
    
    def export_multiple_sessions(
        self,
        sessions: List[Dict[str, Any]]
    ) -> str:
        """
        Export multiple sessions as a single XES log.
        
        Args:
            sessions: List of dicts with 'session_id', 'events', 'metadata'
            
        Returns:
            XES XML string
        """
        log = Element('log')
        log.set('xes.version', '1.0')
        log.set('xes.features', 'nested-attributes')
        log.set('xmlns', self.XES_NAMESPACE)
        
        # Extensions
        self._add_extension(log, 'Concept', 'concept', 'http://www.xes-standard.org/concept.xesext')
        self._add_extension(log, 'Time', 'time', 'http://www.xes-standard.org/time.xesext')
        self._add_extension(log, 'Lifecycle', 'lifecycle', 'http://www.xes-standard.org/lifecycle.xesext')
        
        # Globals
        globals_event = SubElement(log, 'global', scope='event')
        self._add_string_attr(globals_event, 'concept:name', 'UNKNOWN')
        
        # Classifier
        classifier = SubElement(log, 'classifier')
        classifier.set('name', 'Event Name')
        classifier.set('keys', 'concept:name')
        
        # Add each session as a trace
        for session_data in sessions:
            trace = SubElement(log, 'trace')
            self._add_string_attr(trace, 'concept:name', session_data['session_id'])
            
            metadata = session_data.get('metadata', {})
            if metadata.get('tool_id'):
                self._add_string_attr(trace, 'tool:id', metadata['tool_id'])
            if metadata.get('editor_type'):
                self._add_string_attr(trace, 'editor:type', metadata['editor_type'])
            
            for event_data in session_data.get('events', []):
                if not self._should_include(event_data):
                    continue
                    
                event_elem = SubElement(trace, 'event')
                
                # Build full event name
                event_type = event_data.get('event_type', 'UNKNOWN')
                event_kind = event_data.get('event_kind') or ''
                element_type = event_data.get('element_type') or ''
                if element_type:
                    element_type = self._clean_element_type(element_type)
                
                name_parts = [event_type]
                if event_kind:
                    name_parts.append(event_kind)
                if element_type:
                    name_parts.append(element_type)
                event_name = ':'.join(name_parts)
                
                self._add_string_attr(event_elem, 'concept:name', event_name)
                
                ts = event_data.get('timestamp')
                if ts:
                    ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)
                    self._add_date_attr(event_elem, 'time:timestamp', ts_str)
                
                self._add_string_attr(event_elem, 'lifecycle:transition', 'complete')
                
                if event_data.get('element_type'):
                    self._add_string_attr(event_elem, 'element:type', event_data['element_type'])
        
        xml_str = tostring(log, encoding='unicode')
        return minidom.parseString(xml_str).toprettyxml(indent='  ')
    
    def _add_extension(self, parent: Element, name: str, prefix: str, uri: str):
        ext = SubElement(parent, 'extension')
        ext.set('name', name)
        ext.set('prefix', prefix)
        ext.set('uri', uri)
    
    def _add_string_attr(self, parent: Element, key: str, value: str):
        attr = SubElement(parent, 'string')
        attr.set('key', key)
        attr.set('value', value)
    
    def _add_date_attr(self, parent: Element, key: str, value: str):
        attr = SubElement(parent, 'date')
        attr.set('key', key)
        attr.set('value', value)
