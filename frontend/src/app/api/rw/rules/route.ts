export const dynamic = "force-dynamic";
export const revalidate = 0;

export function GET() {
  return Response.json(
    { detail: "R-W mock endpoint disabled; use /api/backend/rw/rules." },
    { status: 410 },
  );
}
