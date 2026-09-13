/**
 * Chinese labels for the topics the backend assigns.
 *
 * The classification itself happens on the server (Phase 10.6) and arrives as
 * `topic`. This module only translates that value for display, so the phone
 * never re-decides what a story is about. An unknown or missing topic falls
 * back to 其他 rather than showing a raw identifier like `model_release`.
 */
const TOPIC_LABELS: Record<string, string> = {
  model_release: '模型',
  agent: 'Agent',
  research: '研究',
  open_source: '开源',
  product: '产品',
  developer_tools: '开发工具',
  hardware: '硬件',
  business: '商业',
  policy: '政策',
  other: '其他',
};

/**
 * The display label for a topic, or an empty string when there is nothing
 * worth showing. `other` is intentionally blank: "we could not classify this"
 * is not information the reader needs on a card.
 */
export function topicLabel(topic: string | null | undefined): string {
  if (!topic) {
    return '';
  }
  const label = TOPIC_LABELS[topic];
  if (!label || topic === 'other') {
    return '';
  }
  return label;
}

export const KNOWN_TOPICS = Object.keys(TOPIC_LABELS);
