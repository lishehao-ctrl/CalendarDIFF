"use client";

import { useEffect } from "react";

export function usePageMetadata(title: string, description?: string | null) {
  useEffect(() => {
    if (typeof document === "undefined") {
      return;
    }

    document.title = title.includes("CalendarDIFF") ? title : `${title} | CalendarDIFF`;

    if (description) {
      const descriptionTag = document.querySelector('meta[name="description"]');
      if (descriptionTag) {
        descriptionTag.setAttribute("content", description);
      }
    }
  }, [description, title]);
}
