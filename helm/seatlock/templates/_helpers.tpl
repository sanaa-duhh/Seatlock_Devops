{{/* Common labels applied to every SeatLock resource. */}}
{{- define "seatlock.labels" -}}
app.kubernetes.io/part-of: seatlock
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end }}

{{/* Image reference: an immutable digest wins over a tag when both are set. */}}
{{- define "seatlock.image" -}}
{{- if .digest -}}
{{ .image }}@{{ .digest }}
{{- else -}}
{{ .image }}:{{ .tag }}
{{- end -}}
{{- end }}
