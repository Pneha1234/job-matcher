import { ComingSoon, PageHeader } from "@/components/page-header";

export const metadata = { title: "Profile · Job Matcher" };

export default function ProfilePage() {
  return (
    <section>
      <PageHeader title="Profile" />
      <ComingSoon phase={1}>
        Upload your resume and add GitHub, portfolio and your LinkedIn export. You review the
        extracted profile before it is saved.
      </ComingSoon>
    </section>
  );
}
