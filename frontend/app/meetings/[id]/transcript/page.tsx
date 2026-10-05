import Link from "next/link";
import { getJurisdiction } from "@/lib/jurisdiction";
import { cache } from "react";
import BodyTag from "@/components/BodyTag";
import TranscriptReader from "@/components/TranscriptReader";
import { api, formatDate } from "@/lib/api";
import { requireRecord } from "@/lib/not-found";

const getTranscript = cache((id: string) => api.transcript(id));

export async function generateMetadata({ params }: { params: { id: string } }) {
  const [t, j] = await Promise.all([requireRecord(getTranscript(params.id)), getJurisdiction()]);
  return {
    title: `Transcript · ${t.title}`,
    description: `The full timestamped transcript of the ${formatDate(t.date)} ${t.title}, with every moment linked to the ${j.identity.noun}'s video.`,
  };
}

export default async function TranscriptPage({
  params,
  searchParams,
}: {
  params: { id: string };
  searchParams: { q?: string };
}) {
  const transcript = await requireRecord(getTranscript(params.id));

  return (
    <div className="mx-auto max-w-[860px] px-4 pb-16 pt-8 sm:px-8">
      <Link href={`/meetings/${params.id}`} className="text-sm font-semibold text-muted hover:text-ink">
        ← Back to the meeting
      </Link>
      <div className="mb-1 mt-4 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[1.5px] text-muted">
        <BodyTag body={transcript.body} /> <span>· {formatDate(transcript.date)}</span>
      </div>
      <h1 className="mb-2 text-[32px] font-medium leading-[1.15] tracking-[-0.5px]">
        {transcript.title}
      </h1>
      <p className="mb-6 max-w-[620px] text-sm leading-[1.6] text-muted">
        Machine transcription of the meeting audio. Timestamps link to that moment on the
        city&apos;s own player — check anything that matters against the recording.
      </p>

      {transcript.video_url && (
        <a
          href={transcript.video_url}
          target="_blank"
          className="mb-2 inline-block rounded-xl bg-ink px-5 py-3 text-sm font-semibold leading-none text-white hover:bg-ink-active"
        >
          ▶ Watch recording
        </a>
      )}

      <TranscriptReader transcript={transcript} initialQuery={searchParams.q ?? ""} />
    </div>
  );
}
