<!--
  CommitteeReviewFeed — scrollable feed of macro committee reviews.

  Shows date, status badge, and truncated summary for each review.
  Terminal tokens only.
-->
<script lang="ts">
  import { formatDate } from "@investintell/ui/utils";

  interface Review {
    id: string;
    status: string;
    createdAt: string;
    summary: string;
  }

  interface Props {
    reviews: Review[];
    onClickReview?: (id: string) => void;
  }

  let { reviews, onClickReview }: Props = $props();

  const STATUS_COLORS: Record<string, string> = {
    approved: "var(--terminal-status-success)",
    pending: "var(--terminal-accent-amber)",
    rejected: "var(--terminal-status-error)",
  };

  function statusColor(s: string): string {
    return STATUS_COLORS[s] ?? "var(--terminal-fg-secondary)";
  }

  function truncate(text: string, max: number): string {
    if (text.length <= max) return text;
    return text.slice(0, max) + "\u2026";
  }
</script>

<div class="cf-root">
  {#each reviews as review (review.id)}
    <button
      type="button"
      class="cf-card"
      onclick={() => onClickReview?.(review.id)}
    >
      <div class="cf-card-header">
        <span class="cf-date">{formatDate(new Date(review.createdAt), "medium")}</span>
        <span class="cf-status" style:color={statusColor(review.status)} style:border-color={statusColor(review.status)}>
          {review.status.toUpperCase()}
        </span>
      </div>
      <p class="cf-summary">{truncate(review.summary, 200)}</p>
    </button>
  {:else}
    <span class="cf-empty">No committee reviews</span>
  {/each}
</div>

<style>
  .cf-root {
    display: flex;
    flex-direction: column;
    gap: var(--terminal-space-2);
    overflow-y: auto;
    height: 100%;
    font-family: var(--terminal-font-mono);
  }

  .cf-card {
    display: flex;
    flex-direction: column;
    gap: var(--terminal-space-1);
    padding: var(--terminal-space-2) var(--terminal-space-3);
    background: var(--terminal-bg-panel);
    border: var(--terminal-border-hairline);
    cursor: pointer;
    text-align: left;
    font-family: var(--terminal-font-mono);
    transition: border-color var(--terminal-motion-tick) var(--terminal-motion-easing-out);
  }

  .cf-card:hover {
    border-color: var(--terminal-accent-amber);
  }

  .cf-card:focus-visible {
    outline: var(--terminal-border-focus);
    outline-offset: -2px;
  }

  .cf-card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--terminal-space-2);
  }

  .cf-date {
    font-size: var(--terminal-text-10);
    color: var(--terminal-fg-secondary);
    font-variant-numeric: tabular-nums;
  }

  .cf-status {
    font-size: var(--terminal-text-10);
    font-weight: 600;
    letter-spacing: var(--terminal-tracking-caps);
    padding: 1px 4px;
    border: 1px solid;
  }

  .cf-summary {
    font-size: var(--terminal-text-11);
    color: var(--terminal-fg-secondary);
    line-height: var(--terminal-leading-normal);
    margin: 0;
  }

  .cf-empty {
    font-size: var(--terminal-text-10);
    color: var(--terminal-fg-muted);
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
    padding: var(--terminal-space-3);
  }
</style>
