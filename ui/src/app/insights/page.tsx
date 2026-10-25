import { ComingSoon, PageHeader } from "@/components/page-header";

export const metadata = { title: "Insights · Job Matcher" };

export default function InsightsPage() {
  return (
    <section>
      <PageHeader title="Insights" aside="Based on your top active matches" />
      <ComingSoon phase={9}>
        Missing skills, your application funnel, matches per day and salary by location.
      </ComingSoon>
    </section>
  );
}
