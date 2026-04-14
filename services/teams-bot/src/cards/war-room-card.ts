import type { WarRoomCreatedPayload, WarRoomAnnotationPayload } from '../types';

/**
 * Build an Adaptive Card for war room creation / operator join events.
 *
 * Schema: Adaptive Card v1.5
 * Layout: header row (⚡ WAR ROOM badge + incident title) + fact set + action buttons
 */
export function buildWarRoomCreatedCard(
  payload: WarRoomCreatedPayload
): Record<string, unknown> {
  const participantNames = payload.participants
    .map((p) => `${p.display_name || p.operator_id} (${p.role})`)
    .join(', ') || 'None yet';

  const facts = [
    { title: 'Incident', value: payload.incident_id },
    { title: 'Severity', value: payload.severity },
    ...(payload.resource_name ? [{ title: 'Resource', value: payload.resource_name }] : []),
    { title: 'Participants', value: participantNames },
  ];

  const actions: Record<string, unknown>[] = [];
  if (payload.incident_url) {
    actions.push({
      type: 'Action.OpenUrl',
      title: 'Open Incident',
      url: payload.incident_url,
    });
  }
  actions.push({
    type: 'Action.OpenUrl',
    title: 'Open War Room',
    url: payload.incident_url
      ? `${payload.incident_url}?war_room=1`
      : `https://aap.example.com/incidents/${payload.incident_id}?war_room=1`,
  });

  return {
    $schema: 'http://adaptivecards.io/schemas/adaptive-card.json',
    type: 'AdaptiveCard',
    version: '1.5',
    body: [
      {
        type: 'ColumnSet',
        columns: [
          {
            type: 'Column',
            width: 'auto',
            items: [
              {
                type: 'TextBlock',
                text: '⚡',
                size: 'Large',
              },
            ],
          },
          {
            type: 'Column',
            width: 'stretch',
            items: [
              {
                type: 'TextBlock',
                text: `WAR ROOM — ${payload.incident_title ?? payload.incident_id}`,
                weight: 'Bolder',
                size: 'Medium',
                wrap: true,
              },
              {
                type: 'TextBlock',
                text: `P0 Incident · Multi-operator collaboration active`,
                size: 'Small',
                isSubtle: true,
                wrap: true,
              },
            ],
          },
        ],
      },
      {
        type: 'FactSet',
        facts,
      },
    ],
    actions,
  };
}

/**
 * Build an Adaptive Card for a new war room annotation / investigation note.
 * Posted as a reply to the Teams war room thread.
 */
export function buildWarRoomAnnotationCard(
  payload: WarRoomAnnotationPayload
): Record<string, unknown> {
  const { annotation } = payload;
  const author = annotation.display_name || annotation.operator_id;
  const time = new Date(annotation.created_at).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  });

  return {
    $schema: 'http://adaptivecards.io/schemas/adaptive-card.json',
    type: 'AdaptiveCard',
    version: '1.5',
    body: [
      {
        type: 'ColumnSet',
        columns: [
          {
            type: 'Column',
            width: 'auto',
            items: [
              {
                type: 'TextBlock',
                text: '📝',
              },
            ],
          },
          {
            type: 'Column',
            width: 'stretch',
            items: [
              {
                type: 'TextBlock',
                text: `**${author}** · ${time}`,
                size: 'Small',
                wrap: true,
              },
              {
                type: 'TextBlock',
                text: annotation.content,
                wrap: true,
                size: 'Small',
              },
              ...(annotation.trace_event_id
                ? [
                    {
                      type: 'TextBlock',
                      text: `📌 Pinned to trace event: ${annotation.trace_event_id}`,
                      size: 'Small',
                      isSubtle: true,
                      wrap: true,
                    },
                  ]
                : []),
            ],
          },
        ],
      },
    ],
  };
}
