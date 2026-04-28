import { NextResponse } from "next/server";
import { dbAvailabilityDetails } from "@/lib/db";
import {
  createLabelForTender,
  getLabelsForTender,
  parseLabelPayload,
} from "@/lib/feedbackLabels";

export const dynamic = "force-dynamic";

function parseId(raw: string): number | null {
  const id = Number(raw);
  if (!Number.isFinite(id) || id < 1) return null;
  return id;
}

export async function GET(
  req: Request,
  ctx: { params: Promise<{ id: string }> },
) {
  const dbState = dbAvailabilityDetails();
  if (!dbState.ok) {
    return NextResponse.json(
      {
        error: "database_unavailable",
        message: dbState.reason,
        checkedPaths: dbState.checkedPaths,
      },
      { status: 503 },
    );
  }
  const { id: idRaw } = await ctx.params;
  const id = parseId(idRaw);
  if (!id) {
    return NextResponse.json(
      { error: "bad_request", message: "invalid id" },
      { status: 400 },
    );
  }
  const url = new URL(req.url);
  const limit = Math.max(1, Math.min(100, Number(url.searchParams.get("limit") ?? "20")));
  try {
    const labels = getLabelsForTender(id, limit);
    return NextResponse.json({ items: labels });
  } catch (e) {
    const msg = e instanceof Error ? e.message : "query failed";
    return NextResponse.json({ error: "server_error", message: msg }, { status: 500 });
  }
}

export async function POST(
  req: Request,
  ctx: { params: Promise<{ id: string }> },
) {
  const dbState = dbAvailabilityDetails();
  if (!dbState.ok) {
    return NextResponse.json(
      {
        error: "database_unavailable",
        message: dbState.reason,
        checkedPaths: dbState.checkedPaths,
      },
      { status: 503 },
    );
  }
  const { id: idRaw } = await ctx.params;
  const id = parseId(idRaw);
  if (!id) {
    return NextResponse.json(
      { error: "bad_request", message: "invalid id" },
      { status: 400 },
    );
  }
  let body: unknown = null;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json(
      { error: "bad_request", message: "invalid JSON body" },
      { status: 400 },
    );
  }
  const parsed = parseLabelPayload(body);
  if ("error" in parsed) {
    return NextResponse.json(
      { error: "bad_request", message: parsed.error },
      { status: 400 },
    );
  }
  try {
    const created = createLabelForTender(id, parsed);
    return NextResponse.json({ label: created }, { status: 201 });
  } catch (e) {
    const msg = e instanceof Error ? e.message : "insert failed";
    if (msg === "tender_not_found") {
      return NextResponse.json({ error: "not_found" }, { status: 404 });
    }
    return NextResponse.json({ error: "server_error", message: msg }, { status: 500 });
  }
}
