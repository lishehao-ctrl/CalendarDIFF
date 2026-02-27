export { ApiError, apiRequest, sanitizeHeaderMap } from "@/lib/api/client";

export { getOnboardingStatus, registerOnboarding } from "@/lib/api/onboarding";
export { getInputs, startGmailOAuth, deleteInput, syncInput } from "@/lib/api/inputs";
export { getEvents } from "@/lib/api/events";
export { getFeed, patchChangeViewed, getEvidencePreview } from "@/lib/api/changes";
export { getEmailReviewQueue, updateEmailRoute, markEmailViewed, applyEmailReview } from "@/lib/api/review";
export { getWorkspaceBootstrap, getHealth } from "@/lib/api/workspace";
