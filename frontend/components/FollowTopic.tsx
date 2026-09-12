"use client";

import FollowButton from "@/components/FollowButton";

/** The original follow-a-topic control, now a thin wrapper over FollowButton. */
export default function FollowTopic({ entitySlug }: { entitySlug: string }) {
  return <FollowButton target={{ kind: "topic", entitySlug }} label="Follow this topic" />;
}
