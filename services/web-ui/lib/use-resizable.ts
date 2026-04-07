import { useCallback, useEffect, useRef, useState } from 'react';

// ---------------------------------------------------------------------------
// Defaults (chat drawer — backwards-compatible when called with no args)
// ---------------------------------------------------------------------------

const DEFAULT_MIN_WIDTH = 360;
const DEFAULT_MAX_WIDTH = 800;
const DEFAULT_DEFAULT_WIDTH = 420;
const DEFAULT_STORAGE_KEY = 'chat-drawer-width';

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export interface UseResizableOptions {
  /** Minimum panel width in px (default 360) */
  readonly minWidth?: number;
  /** Maximum panel width in px (default 800) */
  readonly maxWidth?: number;
  /** Initial width in px when no localStorage value exists (default 420) */
  readonly defaultWidth?: number;
  /** localStorage key for persistence (default 'chat-drawer-width') */
  readonly storageKey?: string;
}

export function useResizable(options?: UseResizableOptions) {
  const minWidth = options?.minWidth ?? DEFAULT_MIN_WIDTH;
  const maxWidth = options?.maxWidth ?? DEFAULT_MAX_WIDTH;
  const defaultWidth = options?.defaultWidth ?? DEFAULT_DEFAULT_WIDTH;
  const storageKey = options?.storageKey ?? DEFAULT_STORAGE_KEY;

  // Always initialise with defaultWidth to match the server render.
  // Read localStorage in useEffect (client-only) to avoid hydration mismatch.
  const [width, setWidth] = useState<number>(defaultWidth);

  useEffect(() => {
    const stored = localStorage.getItem(storageKey);
    const parsed = stored ? parseInt(stored, 10) : NaN;
    if (!isNaN(parsed)) {
      setWidth(Math.min(maxWidth, Math.max(minWidth, parsed)));
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey]);

  const isDragging = useRef(false);
  const startX = useRef(0);
  const startWidth = useRef(0);

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isDragging.current = true;
    startX.current = e.clientX;
    startWidth.current = width;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, [width]);

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!isDragging.current) return;
      // Drawer is on the right side — dragging left increases width
      const delta = startX.current - e.clientX;
      const newWidth = Math.min(maxWidth, Math.max(minWidth, startWidth.current + delta));
      setWidth(newWidth);
    };

    const onMouseUp = () => {
      if (!isDragging.current) return;
      isDragging.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      // Persist to localStorage
      setWidth(prev => {
        if (typeof window !== 'undefined') {
          localStorage.setItem(storageKey, String(prev));
        }
        return prev;
      });
    };

    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
  }, [minWidth, maxWidth, storageKey]);

  return { width, onMouseDown };
}
