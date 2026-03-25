"use client";

import { useEffect, useState } from "react";

export type ResponsiveTier = "mobile" | "tablet" | "desktop";

export function responsiveTierForWidth(width: number): ResponsiveTier {
  if (width < 768) {
    return "mobile";
  }
  if (width < 1280) {
    return "tablet";
  }
  return "desktop";
}

export function useResponsiveTier() {
  const [tier, setTier] = useState<ResponsiveTier>("desktop");

  useEffect(() => {
    function updateTier() {
      setTier(responsiveTierForWidth(window.innerWidth));
    }

    updateTier();
    window.addEventListener("resize", updateTier);
    return () => window.removeEventListener("resize", updateTier);
  }, []);

  return {
    tier,
    isMobile: tier === "mobile",
    isTablet: tier === "tablet",
    isDesktop: tier === "desktop",
    isCompact: tier !== "desktop",
  };
}
