# Debug: chat-panel-scroll-not-working

## Status: FIXED (verified locally with Playwright)

## Symptom
ChatPanel messages area does not scroll when messages overflow. The entire chat panel grows to fit all messages.

## Root Cause Analysis

### Layout Chain (outside-in)
1. `AppLayout.root` - `height: 100vh`, flex column, overflow hidden
2. `AppLayout.mainContent` - `flex: 1`, `minHeight: 0`, overflow hidden
3. `<PanelGroup>` - `height: 100%` (inline style)
4. `<Panel>` (react-resizable-panels) - inline styles: `flex: 35 1 0px`, `overflow: hidden`
5. `AppLayout.chatPanel` class - `position: relative`, `overflow: hidden` (NO `height: 100%`)
6. `ChatPanel.root` - `position: absolute; inset: 0` (fills relative parent)
7. `ChatPanel.messages` - `flex: 1 1 0; minHeight: 0; overflowY: auto; display: flex; flexDirection: column`
8. `ChatPanel.inputArea` - `display: flex; flexDirection: column` (NO flex-shrink/grow constraints)

### Identified Issues

**Issue 1: `chatPanel` missing `height: 100%`**
The Panel wrapper from react-resizable-panels sets `overflow: hidden` via inline styles. The Griffel `chatPanel` class has `position: relative` but no height. Without explicit height, the absolutely-positioned child (`ChatPanel.root`) may not get proper height constraints in all browsers.

**Issue 2: `inputArea` has no flex constraints**
The `inputArea` div (bottom section with chips + input) has `display: flex; flexDirection: column` but no `flexShrink: 0` or `flexGrow: 0`. In a column flex container, this means both `messages` and `inputArea` compete for space. The inputArea should be `flex: 0 0 auto` (don't grow, don't shrink, auto height).

**Issue 3: `messages` div uses `display: flex; flexDirection: column`**
This makes message children participate in flex layout. If the total content exceeds the container, flex children can stretch the parent rather than overflowing. The flex column layout is fine for alignment (flex-start/flex-end) but the key is ensuring the div has a constrained height. The `flex: 1 1 0` + `minHeight: 0` pattern should work IF the parent is a proper flex container with constrained height.

## Fix Applied

1. `ChatPanel.inputArea` - Add `flexShrink: 0` to prevent it from being pushed/squeezed
2. `AppLayout.chatPanel` - Add `height: '100%'` to ensure the relative container fills the Panel
3. Verify the messages container properly scrolls

## Verification
- Playwright test with 50+ mock messages injected via DOM manipulation
- Verify `scrollHeight > clientHeight` on messages container
- Verify scroll position changes when scrolling

### Playwright Test Results (PASS)
All tests passed:
- **Messages container is scrollable**: scrollHeight=1232 > clientHeight=599
- **Input area anchored at bottom**: inputArea.bottom (800) == parent.bottom (800)
- **Messages + input fill parent exactly**: msgHeight (599) + inputHeight (129) == parentHeight (728)
- **Input area below messages**: Confirmed
- **Scroll down**: scrollTop went from 0 to 633
- **Scroll back up**: scrollTop returned to 0
- **Scroll to middle**: scrollTop went to 616

### Files Changed
1. `services/web-ui/components/ChatPanel.tsx` - Added `flexShrink: 0` and `flexGrow: 0` to `inputArea` style
2. `services/web-ui/components/AppLayout.tsx` - Added `height: '100%'` to `chatPanel` style

