{{/*
Expand the name of the chart.
*/}}
{{- define "rag-system.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "rag-system.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "rag-system.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "rag-system.labels" -}}
helm.sh/chart: {{ include "rag-system.chart" . }}
{{ include "rag-system.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "rag-system.selectorLabels" -}}
app.kubernetes.io/name: {{ include "rag-system.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Proxy labels
*/}}
{{- define "rag-system.proxyLabels" -}}
{{ include "rag-system.labels" . }}
app.kubernetes.io/component: proxy
{{- end }}

{{/*
Proxy selector
*/}}
{{- define "rag-system.proxySelector" -}}
{{ include "rag-system.selectorLabels" . }}
app.kubernetes.io/component: proxy
{{- end }}

{{/*
Qdrant labels
*/}}
{{- define "rag-system.qdrantLabels" -}}
{{ include "rag-system.labels" . }}
app.kubernetes.io/component: qdrant
{{- end }}

{{/*
Qdrant selector
*/}}
{{- define "rag-system.qdrantSelector" -}}
{{ include "rag-system.selectorLabels" . }}
app.kubernetes.io/component: qdrant
{{- end }}

{{/*
Neo4j labels
*/}}
{{- define "rag-system.neo4jLabels" -}}
{{ include "rag-system.labels" . }}
app.kubernetes.io/component: neo4j
{{- end }}

{{/*
Neo4j selector
*/}}
{{- define "rag-system.neo4jSelector" -}}
{{ include "rag-system.selectorLabels" . }}
app.kubernetes.io/component: neo4j
{{- end }}

{{/*
Redis labels
*/}}
{{- define "rag-system.redisLabels" -}}
{{ include "rag-system.labels" . }}
app.kubernetes.io/component: redis
{{- end }}

{{/*
Redis selector
*/}}
{{- define "rag-system.redisSelector" -}}
{{ include "rag-system.selectorLabels" . }}
app.kubernetes.io/component: redis
{{- end }}

{{/*
Create the Qdrant API URL
*/}}
{{- define "rag-system.qdrantUrl" -}}
{{- printf "http://%s-qdrant:%d" (include "rag-system.fullname" .) (int .Values.qdrant.service.port) }}
{{- end }}

{{/*
Create the Neo4j bolt URL
*/}}
{{- define "rag-system.neo4jUrl" -}}
{{- printf "bolt://%s-neo4j:%d" (include "rag-system.fullname" .) (int .Values.neo4j.service.boltPort) }}
{{- end }}

{{/*
Create the Redis URL
*/}}
{{- define "rag-system.redisUrl" -}}
{{- printf "redis://%s-redis:%d" (include "rag-system.fullname" .) (int .Values.redis.service.port) }}
{{- end }}

{{/*
Federation labels
*/}}
{{- define "rag-system.federationLabels" -}}
{{ include "rag-system.labels" . }}
app.kubernetes.io/component: federation
{{- end }}

{{/*
Federation selector
*/}}
{{- define "rag-system.federationSelector" -}}
{{ include "rag-system.selectorLabels" . }}
app.kubernetes.io/component: federation
{{- end }}

{{/*
MCP Server labels
*/}}
{{- define "rag-system.mcpServerLabels" -}}
{{ include "rag-system.labels" . }}
app.kubernetes.io/component: mcp-server
{{- end }}

{{/*
MCP Server selector
*/}}
{{- define "rag-system.mcpServerSelector" -}}
{{ include "rag-system.selectorLabels" . }}
app.kubernetes.io/component: mcp-server
{{- end }}

{{/*
MLflow labels
*/}}
{{- define "rag-system.mlflowLabels" -}}
{{ include "rag-system.labels" . }}
app.kubernetes.io/component: mlflow
{{- end }}

{{/*
MinIO labels
*/}}
{{- define "rag-system.minioLabels" -}}
{{ include "rag-system.labels" . }}
app.kubernetes.io/component: minio
{{- end }}
