import { apiRequest } from "@/lib/api/client";
import {
  AppConfig,
  GmailOAuthStartRequest,
  GmailOAuthStartResponse,
  Input,
  ManualSyncResponse,
} from "@/lib/types";

export function getInputs(config: AppConfig): Promise<Input[]> {
  return apiRequest<Input[]>(config, "/v1/inputs");
}

export function startGmailOAuth(
  config: AppConfig,
  payload: GmailOAuthStartRequest = {}
): Promise<GmailOAuthStartResponse> {
  return apiRequest<GmailOAuthStartResponse>(config, "/v1/inputs/email/gmail/oauth/start", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteInput(config: AppConfig, inputId: number): Promise<null> {
  return apiRequest<null>(config, `/v1/inputs/${inputId}`, {
    method: "DELETE",
  });
}

export function syncInput(config: AppConfig, inputId: number): Promise<ManualSyncResponse> {
  return apiRequest<ManualSyncResponse>(config, `/v1/inputs/${inputId}/sync`, {
    method: "POST",
  });
}
