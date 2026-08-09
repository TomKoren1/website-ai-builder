{{- define "backend.fullname" -}}
{{ .Release.Name }}
{{- end -}}

{{- define "backend.labels" -}}
app.kubernetes.io/name: {{ include "backend.fullname" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
