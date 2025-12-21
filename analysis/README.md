# `analysis/` — Interaction Analysis Module

This module provides automated usability analysis on top of stored interaction sessions. It detects behavioral friction patterns, mines event-sequence statistics, exports data for external process-mining tools, and generates eye-tracking heatmaps.

---

## Demo

> `[ PLACEHOLDER  ]`
>
> ![Friction analysis demo](../docs/gifs/analysis_friction_demo.gif)

> `[ PLACEHOLDER ]`
>
> ![Clickstream demo](../docs/gifs/analysis_clickstream_demo.gif)

---

## Features at a Glance

| Feature | Endpoint | Output |
|---|---|---|
| Friction detection | `GET /analysis/friction/{session_id}` | JSON report with score + recommendations |
| Clickstream n-gram analysis | `GET /analysis/clickstream/{session_id}` | Bigrams, trigrams, transition matrix |
| XES export | `GET /analysis/xes/{session_id}` | `.xes` XML file for ProM / Disco / PM4Py |
| Gaze heatmap | `GET /analysis/heatmap/{eye_tracking_session_id}` | PNG image (optionally overlaid on screenshot) |

---

## Friction Detection

### Concept

*Friction* refers to interaction patterns that indicate the user is struggling with the interface — not making progress, undoing mistakes, searching for elements, or expressing frustration through repeated actions. The friction detector identifies four such patterns and scores them on a unified 0–100 scale.

### Detected Patterns

#### 1 · Rage Clicks

Rapid, spatially clustered clicking — the digital equivalent of impatiently hammering a stuck button.

**Detection criteria:**
- ≥ 3 clicks (configurable) within a 1 500 ms window (configurable)
- All clicks fall within a 50 px radius (configurable)

**What it signals:** Unresponsive UI elements, missing visual feedback, or unclear interaction affordances.

---

> `[ PLACEHOLDER ]`
>
> ![Rage click example](../docs/gifs/rage_click_example.gif)

---

#### 2 · Undo/Redo Bursts

Repeated undo and redo operations in quick succession, especially oscillating patterns (`U R U R U R`).

**Detection criteria:**
- ≥ 3 undo/redo operations (configurable) within a 10 s window (configurable)

**Severity boost:** Oscillating `UR` / `RU` patterns are scored higher than pure undo runs.

**What it signals:** Unclear action consequences, lack of preview functionality, or confusing operation semantics.

---

#### 3 · Navigation Thrashing

Erratic, high-frequency viewport changes — panning, zooming, and fitting in rapid succession.

**Detection criteria:**
- ≥ 5 viewport/zoom/scroll changes (configurable) within a 5 s window (configurable)

**What it signals:** Difficulty locating elements, missing minimap or overview panel, poor visual hierarchy in large diagrams.

---

#### 4 · Rapid Deletions

Mass deletion of diagram elements in a short time window, suggesting the user is abandoning their current attempt.

**Detection criteria:**
- ≥ 3 deletions (configurable) within a 3 s window (configurable)

**What it signals:** User frustration, repeated failed attempts, or unclear how to achieve a modeling goal.

---

### Friction Score

Each pattern category produces a sub-score (0–100). The overall score is a weighted combination:

| Category | Weight |
|---|---|
| Rage clicks | 35 % |
| Undo/redo bursts | 30 % |
| Navigation thrashing | 20 % |
| Rapid deletions | 15 % |

**Score interpretation:**

| Range | Interpretation |
|---|---|
| 0 – 20 | Minimal friction — normal, efficient usage |
| 21 – 40 | Low friction — minor issues worth monitoring |
| 41 – 60 | Moderate friction — notable usability concerns |
| 61 – 80 | High friction — user experiencing significant difficulties |
| 81 – 100 | Critical friction — severe problems requiring immediate attention |

---

### Endpoint

```http
GET /analysis/friction/{session_id}
```

The `session_id` can be either the internal UUID or the frontend session ID string (e.g. `activity_2026-01-05T18-20-42.100Z`).

**Optional time bounds** — restrict analysis to a specific window within a session:

```
?start_timestamp=2026-01-05T18:20:42Z&end_timestamp=2026-01-05T18:21:30Z
```

**Tunable detection parameters:**

| Parameter | Default | Range | Description |
|---|---|---|---|
| `rage_click_time_window_ms` | 1500 | 500–5000 | Click cluster time window |
| `rage_click_min_clicks` | 3 | 2–10 | Minimum clicks in a cluster |
| `rage_click_max_radius_px` | 50 | 10–200 | Spatial radius for clustering |
| `undo_redo_time_window_ms` | 10000 | 2000–60000 | Undo/redo burst window |
| `undo_redo_min_operations` | 3 | 2–20 | Minimum operations in a burst |
| `nav_time_window_ms` | 5000 | 1000–30000 | Navigation thrash window |
| `nav_min_changes` | 5 | 3–20 | Minimum viewport changes |
| `deletion_time_window_ms` | 3000 | 1000–10000 | Rapid deletion window |
| `deletion_min_count` | 3 | 2–10 | Minimum deletions |

**Response:**

```json
{
  "session_id":          "activity_2026-01-05T18-20-42.100Z",
  "internal_id":         "uuid",
  "analysis_timestamp":  "2026-01-26T10:00:00Z",
  "total_events_analyzed": 150,
  "friction_percentage": 12.5,
  "friction_score": {
    "overall_score":      35.5,
    "rage_click_score":   20.0,
    "undo_redo_score":    45.0,
    "navigation_score":   30.0,
    "deletion_score":     15.0,
    "interpretation":     "Low friction detected. Some minor usability concerns...",
    "recommendations":   ["Investigate 2 rage click incident(s)..."]
  },
  "rage_clicks":        { "total_events": 2, "events": [...], "hotspot_positions": [...] },
  "undo_redo":          { "total_bursts": 1, "bursts": [...], "common_patterns": [...] },
  "navigation_thrash":  { "total_events": 1, "events": [...] },
  "rapid_deletions":    { "total_events": 0, "events": [] },
  "all_indicators":     [...]
}
```

**Quick start (cURL):**

```bash
# Default config
curl "http://localhost:8000/analysis/friction/activity_2026-01-05T18-20-42.100Z" \
  -H "Authorization: Bearer your-api-key"

# Stricter rage-click threshold
curl "http://localhost:8000/analysis/friction/activity_2026-01-05T18-20-42.100Z?rage_click_min_clicks=4&nav_min_changes=7" \
  -H "Authorization: Bearer your-api-key"
```

**Python:**

```python
import requests

r = requests.get(
    "http://localhost:8000/analysis/friction/activity_2026-01-05T18-20-42.100Z",
    headers={"Authorization": "Bearer your-api-key"},
    params={"rage_click_min_clicks": 4}
)
result = r.json()
print(result["friction_score"]["overall_score"])      # e.g. 35.5
print(result["friction_score"]["interpretation"])
print(result["friction_score"]["recommendations"])
```

---

## Clickstream Analysis

### Concept

Every interaction session is a sequence of events. This endpoint mines that sequence for repeated patterns using **n-gram analysis** and constructs a **transition frequency matrix** — the building blocks for process discovery.

Three granularity levels let you tune how much detail is encoded in each event label:

| `granularity` | Example label |
|---|---|
| `type` | `element_create` |
| `kind` | `element_create:createNode` |
| `full` *(default)* | `element_create:createNode:OpaqueAction` |

### Endpoint

```http
GET /analysis/clickstream/{session_id}
```

| Parameter | Default | Description |
|---|---|---|
| `top_k` | 10 | Number of top n-grams to return (1–50) |
| `granularity` | `full` | Event label granularity (`type` / `kind` / `full`) |
| `start_timestamp` | — | Restrict to events after this time (ISO 8601) |
| `end_timestamp` | — | Restrict to events before this time (ISO 8601) |

**Response:**

```json
{
  "session_id":         "activity_2026-01-05T18-20-42.100Z",
  "total_events":       143,
  "unique_event_types": 11,
  "event_counts": {
    "element_create:createNode:OpaqueAction": 32,
    "property_change:applyLabelEdit":         28
  },
  "top_bigrams": [
    { "sequence": ["element_create:createNode:OpaqueAction", "property_change:applyLabelEdit"],
      "count": 25, "label": "element_create:createNode:OpaqueAction → property_change:applyLabelEdit" }
  ],
  "top_trigrams":    [...],
  "top_transitions": [...],
  "transition_matrix": {
    "element_create:createNode:OpaqueAction": {
      "property_change:applyLabelEdit": 25
    }
  }
}
```

**cURL:**

```bash
# Top 20 patterns, full granularity
curl "http://localhost:8000/analysis/clickstream/my-session-id?top_k=20" \
  -H "Authorization: Bearer your-api-key"

# Coarse view — event type only
curl "http://localhost:8000/analysis/clickstream/my-session-id?granularity=type" \
  -H "Authorization: Bearer your-api-key"
```

---

## XES Export

### Concept

[XES (eXtensible Event Stream)](https://xes-standard.org/) is the standard interchange format for process-mining tools. Exporting sessions as XES allows importing them into **ProM**, **Disco**, **PM4Py**, **Celonis**, **bupaR**, and similar tools for advanced process discovery, conformance checking, and performance analysis.

Each session becomes one *trace* in the XES log. Each interaction event becomes one *event* in that trace.  
Events excluded from the export (low-level noise like raw mouse clicks) are automatically filtered out.

### Event Naming

Events are named using full granularity: `event_type:event_kind:element_type`

Examples:
- `element_create:createNode:OpaqueAction`
- `element_delete:deleteElement`
- `viewport_change:setViewport`

### Endpoint

```http
GET /analysis/xes/{session_id}
```

Returns an `application/xml` file download named `<session_id>.xes`.

Optional time bounds are supported via `start_timestamp` / `end_timestamp`.

**cURL:**

```bash
curl "http://localhost:8000/analysis/xes/my-session-id" \
  -H "Authorization: Bearer your-api-key" \
  -o session.xes
```

**XES snippet:**

```xml
<?xml version="1.0" ?>
<log xes.version="1.0" xmlns="http://www.xes-standard.org/">
  <extension name="Concept" prefix="concept" uri="..."/>
  <extension name="Time"    prefix="time"    uri="..."/>
  <trace>
    <string key="concept:name" value="activity_2026-01-05T18-20-42.100Z"/>
    <string key="tool:id"      value="bigUML"/>
    <string key="editor:type"  value="activity"/>
    <event>
      <string key="concept:name"  value="element_create:createNode:OpaqueAction"/>
      <date   key="time:timestamp" value="2026-01-05T18:20:43.000Z"/>
    </event>
    <!-- ... -->
  </trace>
</log>
```

**Compatible process-mining tools:**

| Tool | Type |
|---|---|
| [ProM](https://promtools.org/) | Academic framework |
| [Disco](https://fluxicon.com/disco/) | Commercial |
| [PM4Py](https://pm4py.fit.fraunhofer.de/) | Python library |
| [bupaR](https://bupar.net/) | R package |
| [Celonis](https://celonis.com/) | Enterprise |

---

## Gaze Heatmap

### Concept

Gaze-point data uploaded via `POST /sessions/eye-tracking` can be rendered as a **kernel-density heatmap**. If a screenshot was uploaded for the same session, the heatmap is automatically overlaid on top of it, giving a direct visual indication of where participants looked during the recording.

### Endpoint

```http
GET /analysis/heatmap/{eye_tracking_session_id}
```

| Parameter | Default | Description |
|---|---|---|
| `sigma` | 18 | Gaussian blur radius — larger = smoother |
| `colormap` | `hot` | Any [Matplotlib colormap](https://matplotlib.org/stable/gallery/color/colormap_reference.html) name |
| `alpha` | 0.45 | Heatmap opacity when overlaid (0–1) |
| `overlay` | `true` | Overlay on screenshot if one is available |
| `filter_border` | `true` | Drop out-of-bounds gaze points (tracker artefacts) |
| `width` / `height` | *(from session)* | Override output image dimensions |
| `start_timestamp` / `end_timestamp` | — | Restrict to a time slice |

**Returns:** PNG image stream (inline display or download).

**cURL:**

```bash
# Default (hot colormap, overlay on screenshot)
curl "http://localhost:8000/analysis/heatmap/my-eye-tracking-session-id" \
  -H "Authorization: Bearer your-api-key" \
  -o heatmap.png

# Custom appearance
curl "http://localhost:8000/analysis/heatmap/my-eye-tracking-session-id?colormap=viridis&sigma=25&alpha=0.6" \
  -H "Authorization: Bearer your-api-key" \
  -o heatmap.png
```

---

## Recognized Event Types

The friction detector maps these types and kinds to behavioral categories. Unknown event types pass through without error — only recognized types contribute to detection.

| Category | `event_type` values | `event_kind` values |
|---|---|---|
| Click / select | `mouse_click`, `element_select` | `elementSelected` |
| Undo | — | `undo`, `UndoAction` |
| Redo | — | `redo`, `RedoAction` |
| Navigation | `viewport_change`, `scroll`, `zoom_change` | `setViewport`, `center`, `fit`, `scroll`, `zoom` |
| Deletion | `element_delete` | `deleteElement`, `delete` |

Spatial analysis of rage clicks requires `position_x` / `position_y` to be present on the event record. The sessions module extracts these automatically from common GLSP action payloads.

---

## Implementation Notes

- All analysis is performed **on-demand** (no background jobs required). Results are computed fresh for each request.
- Detection algorithms use a **sliding-window** approach and handle overlapping clusters without double-counting.
- The `FrictionDetector` and `ClickstreamAnalyzer` classes are fully independent of the web layer and can be used directly in Python scripts or Jupyter notebooks.

```python
from analysis.friction_detector import FrictionDetector
from analysis.schema import FrictionAnalysisConfig

config = FrictionAnalysisConfig(rage_click_min_clicks=4)
detector = FrictionDetector(config)
result = detector.analyze_session(events)          # events: list of dicts
print(result["friction_score"].overall_score)
```
