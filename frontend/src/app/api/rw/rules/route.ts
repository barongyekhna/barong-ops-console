import { rwRulesPayload } from "@/lib/rw-mock-data";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export function GET() {
  return Response.json(rwRulesPayload());
}

