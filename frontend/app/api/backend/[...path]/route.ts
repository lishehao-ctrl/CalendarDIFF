import { NextRequest, NextResponse } from "next/server";

function normalizeBaseUrl(value: string | undefined) {
  return value?.trim().replace(/\/$/, "") || "";
}

async function proxy(request: NextRequest, params: { path?: string[] }) {
  const apiKey = process.env.BACKEND_API_KEY?.trim();
  const baseUrl = normalizeBaseUrl(process.env.BACKEND_BASE_URL);
  const targetPath = (params.path || []).join("/");

  if (!baseUrl || !apiKey) {
    return NextResponse.json(
      {
        detail: "BACKEND_API_KEY and BACKEND_BASE_URL are required"
      },
      { status: 500 }
    );
  }

  const targetUrl = new URL(`${baseUrl}/${targetPath}`);
  request.nextUrl.searchParams.forEach((value, key) => {
    targetUrl.searchParams.set(key, value);
  });

  const body = request.method === "GET" || request.method === "DELETE"
    ? undefined
    : await request.text();

  const response = await fetch(targetUrl, {
    method: request.method,
    headers: {
      "X-API-Key": apiKey,
      "Content-Type": request.headers.get("content-type") || "application/json",
      Cookie: request.headers.get("cookie") || ""
    },
    body,
    cache: "no-store",
    redirect: "manual"
  });

  const text = await response.text();
  const outgoing = new NextResponse(text, {
    status: response.status,
    headers: {
      "Content-Type": response.headers.get("content-type") || "application/json"
    }
  });
  const setCookie = response.headers.get("set-cookie");
  if (setCookie) {
    outgoing.headers.set("set-cookie", setCookie);
  }
  return outgoing;
}

export async function GET(request: NextRequest, context: { params: { path?: string[] } }) {
  return proxy(request, context.params);
}

export async function POST(request: NextRequest, context: { params: { path?: string[] } }) {
  return proxy(request, context.params);
}

export async function PATCH(request: NextRequest, context: { params: { path?: string[] } }) {
  return proxy(request, context.params);
}

export async function DELETE(request: NextRequest, context: { params: { path?: string[] } }) {
  return proxy(request, context.params);
}
