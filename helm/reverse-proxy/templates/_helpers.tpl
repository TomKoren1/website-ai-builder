{{- define "reverse-proxy.fullname" -}}
{{ .Release.Name }}
{{- end -}}

{{- define "reverse-proxy.labels" -}}
app.kubernetes.io/name: {{ include "reverse-proxy.fullname" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
