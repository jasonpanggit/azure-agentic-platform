'use client';

import React, { useState, useEffect } from 'react';
import { MessageBar, MessageBarBody, MessageBarTitle } from '@fluentui/react-components';

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
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', padding: '2rem' }}>
        <MessageBar intent="warning">
          <MessageBarBody>
            <MessageBarTitle>Desktop Required</MessageBarTitle>
            This application requires a desktop browser (minimum 1200px width).
          </MessageBarBody>
        </MessageBar>
      </div>
    );
  }

  return <>{children}</>;
}
