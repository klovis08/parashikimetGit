import { NextResponse } from "next/server";
import { dbAvailabilityDetails } from "@/lib/db";
import { parseTendersSearchParams } from "@/lib/parseTendersParams";
import { queryTendersPage } from "@/lib/queryTenders";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
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

  const url = new URL(req.url);
  const parsed = parseTendersSearchParams(url.searchParams);
  if (!parsed.ok) {
    return NextResponse.json(
      { error: "bad_request", message: parsed.error },
      { status: 400 },
    );
  }

  try {
    const result = queryTendersPage(parsed.value);
    const pageCount = Math.max(
      1,
      Math.ceil(result.total / result.pageSize),
    );
    return NextResponse.json({
      items: result.items,
      page: result.page,
      pageSize: result.pageSize,
      total: result.total,
      pageCount,
      sort: result.sort,
      filters: {
        q: parsed.value.q ?? null,
        authority: parsed.value.authority ?? null,
        cpv: parsed.value.cpv ?? null,
        software: parsed.value.software,
      },
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : "query failed";
    return NextResponse.json(
      { error: "server_error", message: msg },
      { status: 500 },
    );
  }
}
