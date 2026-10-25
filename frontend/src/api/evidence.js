export function analysisStatements(result) {
  return [
    ...result.facts,
    ...result.why_important,
    ...result.risks,
    ...result.opportunities,
    ...result.recommendations,
    ...(result.bank_position ? [result.bank_position] : []),
  ];
}

export function statementEvidence(result, index, ref) {
  if (index === undefined) return null;
  const statement = analysisStatements(result)[Number(index)];
  if (!statement?.source_refs.includes(ref)) return null;
  return statement.evidence_quotes?.[ref] || null;
}

export function featureValue(context, key) {
  const payload = context.payload_json;
  return payload[key] ?? payload.profile_json?.[key] ?? null;
}
