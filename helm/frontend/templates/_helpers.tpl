{{- define "frontend.fullname" -}}
{{ .Release.Name }}
{{- end -}}

{{- define "frontend.labels" -}}
app.kubernetes.io/name: {{ include "frontend.fullname" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
