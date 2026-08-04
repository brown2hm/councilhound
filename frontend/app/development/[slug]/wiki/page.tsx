import { permanentRedirect } from "next/navigation";

/** The wiki is the development page's default tab now — this route exists
 * only so pre-tab deep links keep resolving. */
export default function LegacyProjectWikiPage({
  params,
}: {
  params: { slug: string };
}) {
  permanentRedirect(`/development/${params.slug}`);
}
