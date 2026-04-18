'use client';

import React, { useState, useEffect } from 'react';
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert';
import { Monitor } from 'lucide-react';

interface DesktopOnlyGateProps {
  minWidth: number;
  children: React.ReactNode;
}

export function DesktopOnlyGate({ minWidth, children }: DesktopOnlyGateProps) {
  const [isDesktop, setIsDesktop] = useState(true);

  useEffect(() => {
    const check = () => setIsDesktop(window.innerWidth >= minWidth);
    check();
    window.addEventListener('resize', check);
    return () => window.removeEventListener('resize', check);
  }, [minWidth]);

  if (!isDesktop) {
    return (
      <div className="flex items-center justify-center h-screen p-8 text-center">
        <Alert>
          <Monitor className="h-4 w-4" />
          <AlertTitle className="text-xl font-semibold mb-2">Desktop Required</AlertTitle>
          <AlertDescription className="text-sm text-muted-foreground">
            This application requires a desktop browser (minimum 800px width).
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  return <>{children}</>;
}
