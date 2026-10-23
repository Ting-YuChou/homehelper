import { redirect } from "next/navigation";

// A redirect only; there is nothing to render instantly.
export const instant = false;

export default function AdminPage() {
  redirect("/admin/review");
}
