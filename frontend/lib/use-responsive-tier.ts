"use client";

import { useLayoutEffect, useState } from "react";

export type ResponsiveTier = "mobile" | "tabletPortrait" | "tabletWide" | "desktop";

const DEFAULT_TIER: ResponsiveTier = "tabletPortrait";

export function responsiveTierForWidth(width: number): ResponsiveTier {
  if (width < 768) {
    return "mobile";
  }
  if (width < 1024) {
    return "tabletPortrait";
  }
  if (width < 1280) {
    return "tabletWide";
  }
  return "desktop";
}

export function useResponsiveTier() {
  const [tier, setTier] = useState<ResponsiveTier>(DEFAULT_TIER);
  const [viewportWidth, setViewportWidth] = useState<number | null>(null);
  const [resolved, setResolved] = useState(false);

  useLayoutEffect(() => {
    function updateTier() {
      setViewportWidth(window.innerWidth);
      setTier(responsiveTierForWidth(window.innerWidth));
      setResolved(true);
    }

    updateTier();
    window.addEventListener("resize", updateTier);
    return () => window.removeEventListener("resize", updateTier);
  }, []);

  return {
    tier,
    viewportWidth,
    resolved,
    isMobile: tier === "mobile",
    isTablet: tier === "tabletPortrait" || tier === "tabletWide",
    isTabletPortrait: tier === "tabletPortrait",
    isTabletWide: tier === "tabletWide",
    isDesktop: tier === "desktop",
    isCompact: tier !== "desktop",
  };
}
