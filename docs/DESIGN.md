# Interface system

Both native apps use the same three steps: **Recordings → Query → Results**. Each step has one primary next action. File filters are secondary controls; advanced speech options are collapsed. Results retain source evidence, timestamps and playback. Empty and interrupted states explain the next useful action.

| Token | Value / use |
|---|---|
| Background | `#142c2f` deep teal |
| Surface / raised | `#203d3f` / `#2b4949` |
| Primary action | `#ff9f8f` coral with dark `#2a2b26` text |
| Text / secondary text | `#f1f2e0` / `#b8c9c1` |
| Borders | `#54716e`, coral focus indicator |
| Shape | 8–14 px or dp radii, restrained elevation |
| Type | Native Segoe UI / Android sans; large task title, smaller explanatory copy |

Warm light in the header transitions into teal work surfaces. Coral marks the current step, primary action, selection and progress. Raised buttons and recessed inputs echo the visual reference without putting decorative texture behind reading areas.

Android uses native controls with 48 dp or larger touch targets, scrolling query/settings and filter dialog, plus virtualized file/result lists. The bottom action stays visible. Windows supports keyboard focus, Shift/Ctrl table selection, resizable result panes and a 980×720 minimum window. Color is accompanied by text and checked states.

Implementation: `desktop_theme.py` for Qt; `Ui.java` and `styles.xml` for Android. Keep user-facing copy about the task; describe runtime details in documentation. Screenshots use fictional fixtures. Native controls and contrast checks improve accessibility, but a full assistive-technology audit has not been completed.
