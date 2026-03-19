import React, { useEffect, useRef } from 'react';

export function GraphPaperBackground({ children }: { children: React.ReactNode }) {
  const gridRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const grid = gridRef.current;
    if (!grid) return;

    let animationFrameId: number;
    let lastTime = 0;
    const gridScrollSpeed = 0.5; // pixels per frame for grid
    let gridPosition = 0;

    const animate = (time: number) => {
      if (!lastTime) lastTime = time;
      const delta = time - lastTime;
      lastTime = time;

      // Update position based on time for smooth animation
      gridPosition = (gridPosition + gridScrollSpeed * (delta / 16)) % 80; // 80 = 2x grid size for seamless loop
      
      if (grid) {
        grid.style.backgroundPosition = `0 ${gridPosition}px`;
      }

      animationFrameId = requestAnimationFrame(animate);
    };

    animationFrameId = requestAnimationFrame(animate);

    return () => {
      cancelAnimationFrame(animationFrameId);
    };
  }, []);

  return (
    <div className="relative min-h-screen w-full overflow-hidden bg-black">
      {/* Graph paper grid with animation */}
      <div 
        ref={gridRef}
        className="absolute inset-0 opacity-30 transition-opacity duration-1000 z-4"
        style={{
          backgroundImage: `
            linear-gradient(to right, rgba(255, 255, 255, 0.8) 1px, transparent 1px),
            linear-gradient(to bottom, rgba(255, 255, 255, 0.8) 1px, transparent 1px)
          `,
          backgroundSize: '40px 40px',
          backgroundRepeat: 'repeat',
          backgroundPosition: '0 0',
        }}
      />

      {/* Main content */}
      <div className="relative z-10 min-h-screen w-full">
        {children}
      </div>
    </div>
  );
}
