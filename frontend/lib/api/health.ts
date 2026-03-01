import { apiRequest } from "@/lib/api/client";
import { AppConfig, HealthResponse } from "@/lib/types";

export function getHealth(config: AppConfig): Promise<HealthResponse> {
  return apiRequest<HealthResponse>(config, "/health");
}
