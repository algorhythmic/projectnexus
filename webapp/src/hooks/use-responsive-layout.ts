import { useMediaQuery } from 'usehooks-ts';

export type LayoutMode = 'mobile' | 'tablet' | 'desktop';

export function useResponsiveLayout(): LayoutMode {
  const isMobile = useMediaQuery('(max-width: 767px)');
  const isTablet = useMediaQuery('(min-width: 768px) and (max-width: 1024px)');

  if (isMobile) return 'mobile';
  if (isTablet) return 'tablet';
  return 'desktop';
}
