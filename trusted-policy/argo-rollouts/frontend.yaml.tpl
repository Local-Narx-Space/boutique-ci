{{- $progressive := .Values.progressiveDelivery | default dict -}}
{{- if $progressive.enabled }}
{{- $root := . }}
{{- $services := dict "frontend" 8080 }}
{{- if $progressive.backendsEnabled }}
{{- $_ := set $services "catalogue" 8081 }}
{{- $_ := set $services "cart" 8082 }}
{{- $_ := set $services "orders" 8083 }}
{{- end }}
{{- range $service, $port := $services }}
---
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: {{ $service }}
  namespace: {{ $root.Release.Namespace }}
  labels:
    app.kubernetes.io/name: {{ $service }}
    app.kubernetes.io/part-of: boutique
spec:
  replicas: {{ (index $root.Values $service).replicaCount }}
  revisionHistoryLimit: 3
  minReadySeconds: 5
  progressDeadlineSeconds: 300
  progressDeadlineAbort: true
  selector:
    matchLabels:
      app.kubernetes.io/name: {{ $service }}
  workloadRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {{ $service }}
    scaleDown: onsuccess
  strategy:
    blueGreen:
      activeService: {{ $service }}
      previewService: {{ $service }}-preview
      autoPromotionEnabled: true
      scaleDownDelaySeconds: 600
      scaleDownDelayRevisionLimit: 1
      abortScaleDownDelaySeconds: 30
      prePromotionAnalysis:
        templates:
        - templateName: {{ $service }}-preview-check
        args:
        - name: service-name
          value: {{ $service }}-preview
      postPromotionAnalysis:
        templates:
        - templateName: {{ $service }}-serving-check
        args:
        - name: service-name
          value: {{ $service }}
---
apiVersion: v1
kind: Service
metadata:
  name: {{ $service }}-preview
  namespace: {{ $root.Release.Namespace }}
spec:
  selector:
    app.kubernetes.io/name: {{ $service }}
  ports:
  - name: http
    port: {{ $port }}
    targetPort: http
{{- range $phase := list "preview" "serving" }}
---
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: {{ $service }}-{{ $phase }}-check
  namespace: {{ $root.Release.Namespace }}
spec:
  args:
  - name: service-name
  metrics:
  - name: dependencies-ready
    interval: 10s
    count: {{ if eq $phase "preview" }}3{{ else }}12{{ end }}
    failureLimit: 1
    consecutiveErrorLimit: 1
    successCondition: result.status == 'ok'
    provider:
      web:
        url: {{ printf "http://{{args.service-name}}.%s.svc.cluster.local:%v/health/ready" $root.Release.Namespace $port | quote }}
        timeoutSeconds: 5
  - name: {{ if eq $service "frontend" }}functional-checkout{{ else }}functional-service{{ end }}
    interval: 30s
    count: {{ if eq $phase "preview" }}1{{ else }}3{{ end }}
    failureLimit: 0
    consecutiveErrorLimit: 1
    provider:
      job:
        spec:
          backoffLimit: 0
          activeDeadlineSeconds: 90
          ttlSecondsAfterFinished: 3600
          template:
            metadata:
              labels:
                app.kubernetes.io/name: {{ if eq $service "frontend" }}frontend{{ else }}backend{{ end }}-rollout-analysis
            spec:
              serviceAccountName: frontend-rollout-analysis
              automountServiceAccountToken: false
              restartPolicy: Never
              imagePullSecrets:
              - name: ghcr-pull
              securityContext:
                runAsNonRoot: true
                runAsUser: 1000
                runAsGroup: 1000
              containers:
              - name: checkout
                image: ghcr.io/subhankar12-spec/boutique-frontend@sha256:719736fb72cf4aac5131630374ab44fcd1aa7a365250bfbf40caacda4cca25aa
                command: [node, /analysis/{{ if eq $service "frontend" }}checkout-check{{ else }}backend-check{{ end }}.mjs]
                env:
                - name: BASE_URL
                  value: {{ printf "http://{{args.service-name}}.%s.svc.cluster.local:%v" $root.Release.Namespace $port | quote }}
                {{- if eq $service "frontend" }}
                - name: PUBLIC_ORIGIN
                  value: {{- range (index $root.Values.frontend.deployment.template.spec.containers 0).env }}{{ if eq .name "PUBLIC_ORIGIN" }} {{ .value | quote }}{{ end }}{{- end }}
                {{- else }}
                - name: SERVICE
                  value: {{ $service | quote }}
                {{- end }}
                resources:
                  requests: {cpu: 25m, memory: 32Mi}
                  limits: {cpu: 250m, memory: 96Mi}
                securityContext:
                  allowPrivilegeEscalation: false
                  readOnlyRootFilesystem: true
                  capabilities:
                    drop: [ALL]
                  seccompProfile:
                    type: RuntimeDefault
                volumeMounts:
                - name: analysis
                  mountPath: /analysis
                  readOnly: true
              volumes:
              - name: analysis
                configMap:
                  name: frontend-rollout-analysis
  {{- if eq $service "frontend" }}
  - name: browse-products
    interval: 10s
    count: {{ if eq $phase "preview" }}3{{ else }}12{{ end }}
    failureLimit: 1
    consecutiveErrorLimit: 1
    successCondition: len(result) > 0 && result[0].id != '' && result[0].price > 0
    provider:
      web:
        url: {{ printf "http://{{args.service-name}}.%s.svc.cluster.local:8080/api/products" $root.Release.Namespace | quote }}
        timeoutSeconds: 5
  {{- end }}
{{- end }}
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ $service }}-progressive-checks
  namespace: {{ $root.Release.Namespace }}
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: {{ $service }}
  policyTypes: [Ingress]
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app.kubernetes.io/name: argo-rollouts
    - podSelector:
        matchLabels:
          app.kubernetes.io/name: frontend-rollout-analysis
    {{- if ne $service "frontend" }}
    - podSelector:
        matchLabels:
          app.kubernetes.io/name: backend-rollout-analysis
    {{- end }}
    ports:
    - protocol: TCP
      port: {{ $port }}
{{- end }}
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: frontend-rollout-analysis
  namespace: {{ .Release.Namespace }}
automountServiceAccountToken: false
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: frontend-rollout-analysis
  namespace: {{ .Release.Namespace }}
data:
  checkout-check.mjs: |
{{ .Files.Get "analysis/checkout-check.mjs" | indent 4 }}
{{- if $progressive.backendsEnabled }}
  backend-check.mjs: |
{{ .Files.Get "analysis/backend-check.mjs" | indent 4 }}
{{- end }}
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: progressive-controller
  namespace: {{ .Release.Namespace }}
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: argo-rollouts
  policyTypes: [Ingress, Egress]
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: monitoring
    ports:
    - protocol: TCP
      port: 8090
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
  - to:
    - podSelector:
        matchLabels:
          app.kubernetes.io/name: frontend
    ports:
    - protocol: TCP
      port: 8080
  - to:
    - ipBlock:
        cidr: {{ required "progressiveDelivery.apiServerCIDR must identify the Kubernetes API endpoint" $progressive.apiServerCIDR | quote }}
    ports:
    - protocol: TCP
      port: 6443
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: frontend-rollout-analysis
  namespace: {{ .Release.Namespace }}
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: frontend-rollout-analysis
  policyTypes: [Ingress, Egress]
  ingress: []
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
  - to:
    - podSelector:
        matchLabels:
          app.kubernetes.io/name: frontend
    ports:
    - protocol: TCP
      port: 8080
{{- if $progressive.backendsEnabled }}
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: backend-progressive-egress
  namespace: {{ .Release.Namespace }}
spec:
  podSelector:
    matchExpressions:
    - key: app.kubernetes.io/name
      operator: In
      values: [argo-rollouts, backend-rollout-analysis]
  policyTypes: [Egress]
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
{{- range $service, $port := dict "catalogue" 8081 "cart" 8082 "orders" 8083 }}
  - to:
    - podSelector:
        matchLabels:
          app.kubernetes.io/name: {{ $service }}
    ports:
    - protocol: TCP
      port: {{ $port }}
{{- end }}
{{- end }}
{{- end }}
