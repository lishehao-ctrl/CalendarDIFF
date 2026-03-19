"use client";

export const PREVIEW_BASE_PATH = "/preview";

export function isPreviewPath(pathname: string | null | undefined) {
  return typeof pathname === "string" && (pathname === PREVIEW_BASE_PATH || pathname.startsWith(`${PREVIEW_BASE_PATH}/`));
}

export function getClientPreviewMode() {
  if (typeof window === "undefined") {
    return false;
  }
  return isPreviewPath(window.location.pathname);
}

export function withBasePath(basePath: string | undefined, href: string) {
  const normalizedBase = (basePath || "").replace(/\/$/, "");
  if (!normalizedBase) {
    return href;
  }
  if (href === "/") {
    return normalizedBase || "/";
  }
  return `${normalizedBase}${href.startsWith("/") ? href : `/${href}`}`;
}
