import { NextResponse } from "next/server";
import { dbAvailabilityDetails } from "@/lib/db";
import { computeRegistryStats } from "@/lib/stats";

export const dynamic = "force-dynamic";

export async function GET() {
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

  try {
    const stats = computeRegistryStats();
    return NextResponse.json(stats);
  } catch (e) {
    const msg = e instanceof Error ? e.message : "stats failed";
    return NextResponse.json(
      { error: "server_error", message: msg },
      { status: 500 },
    );
  }
}
