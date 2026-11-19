"use client"

import * as React from "react"
import { PlusIcon, Trash2Icon, GripVerticalIcon } from "lucide-react"
import * as yaml from "js-yaml"

import { Button } from "@workspace/ui/components/button"
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@workspace/ui/components/field"
import { Input } from "@workspace/ui/components/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@workspace/ui/components/table"
import { Separator } from "@workspace/ui/components/separator"
import { CodeEditor } from "@workspace/ui/components/athena/code-editor"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@workspace/ui/components/tabs"
import { Badge } from "@workspace/ui/components/badge"

type PortMapping = { host: string; container: string; protocol: "tcp" | "udp" }
type VolumeMapping = { host: string; container: string; mode?: "ro" | "rw" }
type EnvVar = { key: string; value: string }
type ResourceLimits = { cpus?: string; memory?: string }
type HealthCheck = { test: string; interval?: string; timeout?: string; retries?: number; start_period?: string }

interface ServiceForm {
  name: string
  image: string
  ports: PortMapping[]
  volumes: VolumeMapping[]
  environment: EnvVar[]
  restart: "no" | "always" | "unless-stopped" | "on-failure"
  command: string
  entrypoint: string
  working_dir: string
  user: string
  deploy: {
    resources: {
      limits: ResourceLimits
      reservations: ResourceLimits
    }
  }
  healthcheck: HealthCheck | null
  labels: EnvVar[]
  networks: string[]
  depends_on: string[]
}

interface ComposeFormData {
  services: Record<string, ServiceForm>
  networks: Record<string, { driver?: string; external?: boolean }>
  volumes: Record<string, { driver?: string; external?: boolean }>
}

const DEFAULT_SERVICE: ServiceForm = {
  name: "web",
  image: "",
  ports: [],
  volumes: [],
  environment: [],
  restart: "unless-stopped",
  command: "",
  entrypoint: "",
  working_dir: "",
  user: "",
  deploy: {
    resources: {
      limits: {},
      reservations: {},
    },
  },
  healthcheck: null,
  labels: [],
  networks: [],
  depends_on: [],
}

const RESTART_OPTIONS = [
  { value: "no", label: "No (don't restart)" },
  { value: "always", label: "Always" },
  { value: "unless-stopped", label: "Unless stopped" },
  { value: "on-failure", label: "On failure" },
] as const

const PROTOCOL_OPTIONS = [
  { value: "tcp", label: "TCP" },
  { value: "udp", label: "UDP" },
] as const

const VOLUME_MODE_OPTIONS = [
  { value: "rw", label: "Read/Write" },
  { value: "ro", label: "Read-only" },
] as const

interface ParsedService {
  image?: string
  ports?: Array<string | { target: number | string; published?: number | string; protocol?: string }>
  volumes?: Array<string | { source: string; target: string; read_only?: boolean }>
  environment?: Record<string, string | number | null> | Array<string>
  restart?: string
  command?: string | string[]
  entrypoint?: string | string[]
  working_dir?: string
  user?: string
  deploy?: {
    resources?: {
      limits?: { cpus?: number | string; memory?: string }
      reservations?: { cpus?: number | string; memory?: string }
    }
  }
  healthcheck?: {
    test?: string | string[]
    interval?: string
    timeout?: string
    retries?: number
    start_period?: string
  }
  labels?: Record<string, string> | Array<string>
  networks?: string[]
  depends_on?: string[] | Record<string, { required?: boolean; condition?: string }>
}

interface ParsedCompose {
  services?: Record<string, ParsedService>
  networks?: Record<string, { driver?: string; external?: boolean }>
  volumes?: Record<string, { driver?: string; external?: boolean }>
}

function parseComposeToForm(text: string): ComposeFormData {
  try {
    const doc = yaml.load(text) as ParsedCompose
    if (!doc || typeof doc !== "object") return { services: {}, networks: {}, volumes: {} }

    const services: Record<string, ServiceForm> = {}
    for (const [name, svc] of Object.entries(doc.services || {})) {
      if (!svc || typeof svc !== "object") continue

      const ports: PortMapping[] = []
      for (const port of svc.ports || []) {
        if (typeof port === "string") {
          const match = port.match(/^(?:(\d+):)?(\d+)(?:\/(\w+))?$/)
          if (match) {
            ports.push({
              host: match[1] || "",
              container: match[2] || "",
              protocol: (match[3] as "tcp" | "udp") || "tcp",
            })
          }
        } else if (typeof port === "object" && port.target) {
          ports.push({
            host: String(port.published || ""),
            container: String(port.target),
            protocol: (port.protocol as "tcp" | "udp") || "tcp",
          })
        }
      }

      const volumes: VolumeMapping[] = []
      for (const vol of svc.volumes || []) {
        if (typeof vol === "string") {
          const parts = vol.split(":")
          if (parts.length >= 2) {
            volumes.push({
              host: parts[0] || "",
              container: parts[1] || "",
              mode: (parts[2] as "ro" | "rw") || "rw",
            })
          }
        } else if (typeof vol === "object" && vol.source && vol.target) {
          volumes.push({
            host: vol.source,
            container: vol.target,
            mode: (vol.read_only ? "ro" : "rw") as "ro" | "rw",
          })
        }
      }

      const environment: EnvVar[] = []
      if (svc.environment) {
        if (Array.isArray(svc.environment)) {
          for (const env of svc.environment) {
            if (typeof env === "string") {
              const idx = env.indexOf("=")
              if (idx > 0) {
                environment.push({ key: env.slice(0, idx), value: env.slice(idx + 1) })
              } else {
                environment.push({ key: env, value: "" })
              }
            }
          }
        } else if (typeof svc.environment === "object") {
          for (const [key, value] of Object.entries(svc.environment)) {
            environment.push({ key, value: String(value ?? "") })
          }
        }
      }

      const labels: EnvVar[] = []
      if (svc.labels) {
        if (Array.isArray(svc.labels)) {
          for (const label of svc.labels) {
            if (typeof label === "string") {
              const idx = label.indexOf("=")
              if (idx > 0) {
                labels.push({ key: label.slice(0, idx), value: label.slice(idx + 1) })
              }
            }
          }
        } else if (typeof svc.labels === "object") {
          for (const [key, value] of Object.entries(svc.labels)) {
            labels.push({ key, value: String(value ?? "") })
          }
        }
      }

      let healthcheck: HealthCheck | null = null
      if (svc.healthcheck) {
        const hc = svc.healthcheck
        healthcheck = {
          test: Array.isArray(hc.test) ? hc.test.join(" ") : String(hc.test || ""),
          interval: hc.interval,
          timeout: hc.timeout,
          retries: hc.retries,
          start_period: hc.start_period,
        }
      }

      const dependsOn: string[] = []
      if (svc.depends_on) {
        if (Array.isArray(svc.depends_on)) {
          dependsOn.push(...svc.depends_on)
        } else if (typeof svc.depends_on === "object") {
          dependsOn.push(...Object.keys(svc.depends_on))
        }
      }

      services[name] = {
        name,
        image: svc.image || "",
        ports,
        volumes,
        environment,
        restart: (svc.restart as ServiceForm["restart"]) || "unless-stopped",
        command: Array.isArray(svc.command) ? svc.command.join(" ") : String(svc.command || ""),
        entrypoint: Array.isArray(svc.entrypoint) ? svc.entrypoint.join(" ") : String(svc.entrypoint || ""),
        working_dir: svc.working_dir || "",
        user: svc.user || "",
        deploy: {
          resources: {
            limits: {
              cpus: svc.deploy?.resources?.limits?.cpus ? String(svc.deploy.resources.limits.cpus) : "",
              memory: svc.deploy?.resources?.limits?.memory ? String(svc.deploy.resources.limits.memory) : "",
            },
            reservations: {
              cpus: svc.deploy?.resources?.reservations?.cpus ? String(svc.deploy.resources.reservations.cpus) : "",
              memory: svc.deploy?.resources?.reservations?.memory ? String(svc.deploy.resources.reservations.memory) : "",
            },
          },
        },
        healthcheck,
        labels,
        networks: svc.networks || [],
        depends_on: dependsOn,
      }
    }

    return {
      services,
      networks: doc.networks || {},
      volumes: doc.volumes || {},
    }
  } catch {
    return { services: {}, networks: {}, volumes: {} }
  }
}

function serializeFormToCompose(form: ComposeFormData): string {
  const doc: Record<string, any> = {
    services: {},
    networks: {},
    volumes: {},
  }

  for (const [name, svc] of Object.entries(form.services)) {
    const service: Record<string, any> = { image: svc.image }

    if (svc.ports.length) {
      service.ports = svc.ports
        .filter((p) => p.container)
        .map((p) => {
          const parts = []
          if (p.host) parts.push(p.host)
          parts.push(`${p.container}/${p.protocol}`)
          return parts.join(":")
        })
    }

    if (svc.volumes.length) {
      service.volumes = svc.volumes
        .filter((v) => v.container)
        .map((v) => {
          const parts = [v.host, v.container]
          if (v.mode && v.mode !== "rw") parts.push(v.mode)
          return parts.join(":")
        })
    }

    if (svc.environment.length) {
      service.environment = svc.environment
        .filter((e) => e.key)
        .map((e) => `${e.key}=${e.value}`)
    }

    if (svc.restart && svc.restart !== "unless-stopped") {
      service.restart = svc.restart
    }

    if (svc.command) service.command = svc.command.split(/\s+/).filter(Boolean)
    if (svc.entrypoint) service.entrypoint = svc.entrypoint.split(/\s+/).filter(Boolean)
    if (svc.working_dir) service.working_dir = svc.working_dir
    if (svc.user) service.user = svc.user

    if (svc.deploy.resources.limits.cpus || svc.deploy.resources.limits.memory) {
      service.deploy = {
        resources: {
          limits: {},
        },
      }
      if (svc.deploy.resources.limits.cpus) service.deploy.resources.limits.cpus = parseFloat(svc.deploy.resources.limits.cpus)
      if (svc.deploy.resources.limits.memory) service.deploy.resources.limits.memory = svc.deploy.resources.limits.memory
      if (svc.deploy.resources.reservations.cpus || svc.deploy.resources.reservations.memory) {
        service.deploy.resources.reservations = {}
        if (svc.deploy.resources.reservations.cpus) service.deploy.resources.reservations.cpus = parseFloat(svc.deploy.resources.reservations.cpus)
        if (svc.deploy.resources.reservations.memory) service.deploy.resources.reservations.memory = svc.deploy.resources.reservations.memory
      }
    }

    if (svc.healthcheck && svc.healthcheck.test) {
      service.healthcheck = {
        test: svc.healthcheck.test.split(/\s+/).filter(Boolean),
        interval: svc.healthcheck.interval,
        timeout: svc.healthcheck.timeout,
        retries: svc.healthcheck.retries,
        start_period: svc.healthcheck.start_period,
      }
    }

    if (svc.labels.length) {
      service.labels = svc.labels.filter((l) => l.key).map((l) => `${l.key}=${l.value}`)
    }

    if (svc.networks.length) service.networks = svc.networks
    if (svc.depends_on.length) service.depends_on = svc.depends_on.filter(Boolean)

    doc.services[name] = service
  }

  if (Object.keys(form.networks).length) doc.networks = form.networks
  if (Object.keys(form.volumes).length) doc.volumes = form.volumes

  return yaml.dump(doc, { indent: 2, lineWidth: -1, noRefs: true, sortKeys: true })
}

type PortMappingWithId = PortMapping & { id: string }
type VolumeMappingWithId = VolumeMapping & { id: string }
type EnvVarWithId = EnvVar & { id: string }
type NetworkWithId = { name: string; driver: string; external: boolean; id: string }
type VolumeWithId = { name: string; driver: string; external: boolean; id: string }

function EditableTable<T extends { id: string }>({
  items,
  onChange,
  renderRow,
  addItem,
  emptyMessage = "No items yet",
  columns,
}: {
  items: T[]
  onChange: (items: T[]) => void
  renderRow: (item: T, index: number, moveUp: () => void, moveDown: () => void, remove: () => void) => React.ReactNode
  addItem: () => T
  emptyMessage?: string
  columns: string[]
}) {
  const moveUp = (index: number) => {
    if (index === 0) return
    const newItems = [...items]
    const [prev, curr] = [newItems[index - 1], newItems[index]]
    newItems[index] = prev!
    newItems[index - 1] = curr!
    onChange(newItems)
  }

  const moveDown = (index: number) => {
    if (index === items.length - 1) return
    const newItems = [...items]
    const [curr, next] = [newItems[index], newItems[index + 1]]
    newItems[index] = next!
    newItems[index + 1] = curr!
    onChange(newItems)
  }

  const remove = (index: number) => {
    onChange(items.filter((_, i) => i !== index))
  }

  return (
    <div className="border rounded-lg overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow>
            {columns.map((col) => <TableHead key={col}>{col}</TableHead>)}
            <TableHead className="w-24">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.length === 0 ? (
            <TableRow>
              <TableCell colSpan={columns.length + 1} className="text-center text-muted-foreground py-8">
                {emptyMessage}
              </TableCell>
            </TableRow>
          ) : (
            items.map((item, index) => (
              <TableRow key={item.id}>
                {renderRow(
                  item,
                  index,
                  () => moveUp(index),
                  () => moveDown(index),
                  () => remove(index),
                )}
                <TableCell>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => moveUp(index)}
                      disabled={index === 0}
                      aria-label="Move up"
                    >
                      <GripVerticalIcon className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => moveDown(index)}
                      disabled={index === items.length - 1}
                      aria-label="Move down"
                    >
                      <GripVerticalIcon className="h-4 w-4 rotate-180" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => remove(index)}
                      aria-label="Remove"
                    >
                      <Trash2Icon className="h-4 w-4" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
      <Button variant="outline" size="sm" onClick={() => onChange([...items, addItem()])} className="w-full">
        <PlusIcon className="h-4 w-4 mr-2" />
        Add
      </Button>
    </div>
  )
}

function ServiceFormComponent({
  service,
  index,
  onChange,
  serviceNames,
  allServiceNames,
}: {
  service: ServiceForm
  index: number
  onChange: (service: ServiceForm) => void
  serviceNames: string[]
  allServiceNames: string[]
}) {
  const [expanded, setExpanded] = React.useState(true)

  const updateService = (updates: Partial<ServiceForm>) => {
    onChange({ ...service, ...updates })
  }

  type ArrayField = "ports" | "volumes" | "environment" | "labels" | "networks" | "depends_on"

  const updateArrayField = <T extends { id: string }>(field: ArrayField, items: T[]) => {
    onChange({ ...service, [field]: items.map(({ id, ...rest }) => rest) } as ServiceForm)
  }

  const updateArrayItem = <T extends { id: string }>(field: ArrayField, index: number, item: T) => {
    const current = service[field] as unknown as T[]
    const next = [...current]
    next[index] = item
    updateArrayField(field, next)
  }

  return (
    <div className="border rounded-lg overflow-hidden">
      <div className="flex items-center justify-between p-4 bg-muted/50 border-b">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setExpanded(!expanded)}
            aria-label={expanded ? "Collapse" : "Expand"}
          >
            {expanded ? "▼" : "▶"}
          </Button>
          <Input
            value={service.name}
            onChange={(e) => updateService({ name: e.target.value })}
            placeholder="service name"
            className="w-48 font-mono text-sm"
            disabled={index > 0}
          />
          <Badge variant="secondary">{service.image || "no image"}</Badge>
        </div>
        <Button variant="ghost" size="icon" onClick={() => {}} disabled>
          <Trash2Icon className="h-4 w-4" />
        </Button>
      </div>

      {expanded && (
        <div className="p-4 space-y-6">
          <Separator />
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor={`service-${index}-image`}>Image</FieldLabel>
              <FieldContent>
                <Input
                  id={`service-${index}-image`}
                  value={service.image}
                  onChange={(e) => updateService({ image: e.target.value })}
                  placeholder="nginx:alpine, ghcr.io/user/repo:tag"
                />
                <FieldDescription>
                  Docker image name. Supports Docker Hub, GHCR, and other registries.
                </FieldDescription>
              </FieldContent>
            </Field>

            <Field>
              <FieldLabel htmlFor={`service-${index}-restart`}>Restart policy</FieldLabel>
              <FieldContent>
                <Select value={service.restart} onValueChange={(v) => updateService({ restart: v as any })} >
                  <SelectTrigger id={`service-${index}-restart`}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {RESTART_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </FieldContent>
            </Field>
          </FieldGroup>

          <Separator />
          <Field>
            <FieldLabel>Ports</FieldLabel>
            <FieldContent>
              <EditableTable<PortMappingWithId>
                items={service.ports.map((p, i) => ({ ...p, id: `port-${i}` }))}
                onChange={(items) => updateArrayField("ports", items)}
                addItem={() => ({ host: "", container: "", protocol: "tcp", id: `port-${Date.now()}` })}
                columns={["Host port", "Container port", "Protocol"]}
                renderRow={(item, idx, moveUp, moveDown, remove) => (
                  <>
                    <TableCell>
                      <Input
                        placeholder="8080"
                        value={item.host}
                        onChange={(e) =>
                          updateArrayItem("ports", idx, { ...item, host: e.target.value })
                        }
                      />
                    </TableCell>
                    <TableCell>
                      <Input
                        placeholder="80"
                        value={item.container}
                        onChange={(e) =>
                          updateArrayItem("ports", idx, { ...item, container: e.target.value })
                        }
                        required
                      />
                    </TableCell>
                    <TableCell>
                      <Select value={item.protocol} onValueChange={(v) => updateArrayItem("ports", idx, { ...item, protocol: v as any })}>
                        <SelectTrigger className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {PROTOCOL_OPTIONS.map((opt) => (
                            <SelectItem key={opt.value} value={opt.value}>
                              {opt.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </TableCell>
                  </>
                )}
              />
              <FieldDescription>
                Map host ports to container ports. Leave host port empty for random assignment.
              </FieldDescription>
            </FieldContent>
          </Field>

          <Separator />
          <Field>
            <FieldLabel>Volumes</FieldLabel>
            <FieldContent>
              <EditableTable<VolumeMappingWithId>
                items={service.volumes.map((v, i) => ({ ...v, id: `vol-${i}` }))}
                onChange={(items) => updateArrayField("volumes", items)}
                addItem={() => ({ host: "", container: "", mode: "rw", id: `vol-${Date.now()}` })}
                columns={["Host path / Volume name", "Container path", "Mode"]}
                renderRow={(item, idx, moveUp, moveDown, remove) => (
                  <>
                    <TableCell>
                      <Input
                        placeholder={"${ATHENA_APP_DATA}/data or volume-name"}
                        value={item.host}
                        onChange={(e) =>
                          updateArrayItem("volumes", idx, { ...item, host: e.target.value })
                        }
                      />
                    </TableCell>
                    <TableCell>
                      <Input
                        placeholder="/data"
                        value={item.container}
                        onChange={(e) =>
                          updateArrayItem("volumes", idx, { ...item, container: e.target.value })
                        }
                        required
                      />
                    </TableCell>
                    <TableCell>
                      <Select value={item.mode || "rw"} onValueChange={(v) => updateArrayItem("volumes", idx, { ...item, mode: v as any })}>
                        <SelectTrigger className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {VOLUME_MODE_OPTIONS.map((opt) => (
                            <SelectItem key={opt.value} value={opt.value}>
                              {opt.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </TableCell>
                  </>
                )}
              />
              <FieldDescription>
                Bind-mount host paths or named volumes. Use <code>{"${ATHENA_APP_DATA}"}</code> for this app's data folder.
              </FieldDescription>
            </FieldContent>
          </Field>

          <Separator />
          <Field>
            <FieldLabel>Environment variables</FieldLabel>
            <FieldContent>
              <EditableTable<EnvVarWithId>
                items={service.environment.map((e, i) => ({ ...e, id: `env-${i}` }))}
                onChange={(items) => updateArrayField("environment", items)}
                addItem={() => ({ key: "", value: "", id: `env-${Date.now()}` })}
                columns={["Key", "Value"]}
                renderRow={(item, idx, moveUp, moveDown, remove) => (
                  <>
                    <TableCell>
                      <Input
                        placeholder="VAR_NAME"
                        value={item.key}
                        onChange={(e) =>
                          updateArrayItem("environment", idx, { ...item, key: e.target.value })
                        }
                      />
                    </TableCell>
                    <TableCell>
                      <Input
                        placeholder="value"
                        value={item.value}
                        onChange={(e) =>
                          updateArrayItem("environment", idx, { ...item, value: e.target.value })
                        }
                      />
                    </TableCell>
                  </>
                )}
              />
              <FieldDescription>
                Environment variables passed to the container. Values from the install form (.env) are also available.
              </FieldDescription>
            </FieldContent>
          </Field>

          <Separator />
          <div className="grid gap-4 md:grid-cols-2">
            <Field>
              <FieldLabel htmlFor={`service-${index}-command`}>Command</FieldLabel>
              <FieldContent>
                <Input
                  id={`service-${index}-command`}
                  value={service.command}
                  onChange={(e) => updateService({ command: e.target.value })}
                  placeholder="Overrides the image's default command"
                />
              </FieldContent>
            </Field>
            <Field>
              <FieldLabel htmlFor={`service-${index}-entrypoint`}>Entrypoint</FieldLabel>
              <FieldContent>
                <Input
                  id={`service-${index}-entrypoint`}
                  value={service.entrypoint}
                  onChange={(e) => updateService({ entrypoint: e.target.value })}
                  placeholder="Overrides the image's default entrypoint"
                />
              </FieldContent>
            </Field>
            <Field>
              <FieldLabel htmlFor={`service-${index}-working-dir`}>Working directory</FieldLabel>
              <FieldContent>
                <Input
                  id={`service-${index}-working-dir`}
                  value={service.working_dir}
                  onChange={(e) => updateService({ working_dir: e.target.value })}
                  placeholder="/app"
                />
              </FieldContent>
            </Field>
            <Field>
              <FieldLabel htmlFor={`service-${index}-user`}>User</FieldLabel>
              <FieldContent>
                <Input
                  id={`service-${index}-user`}
                  value={service.user}
                  onChange={(e) => updateService({ user: e.target.value })}
                  placeholder="1000:1000"
                />
              </FieldContent>
            </Field>
          </div>

          <Separator />
          <Field>
            <FieldLabel>Resource limits</FieldLabel>
            <FieldContent>
              <div className="grid gap-4 md:grid-cols-4">
                <Field>
                  <FieldLabel htmlFor={`service-${index}-limit-cpus`}>CPU limit</FieldLabel>
                  <FieldContent>
                    <Input
                      id={`service-${index}-limit-cpus`}
                      type="number"
                      step="0.1"
                      min="0"
                      value={service.deploy.resources.limits.cpus || ""}
                      onChange={(e) =>
                        updateService({
                          deploy: {
                            ...service.deploy,
                            resources: {
                              ...service.deploy.resources,
                              limits: { ...service.deploy.resources.limits, cpus: e.target.value },
                            },
                          },
                        })
                      }
                      placeholder="1.0"
                    />
                    <FieldDescription>CPU cores</FieldDescription>
                  </FieldContent>
                </Field>
                <Field>
                  <FieldLabel htmlFor={`service-${index}-limit-memory`}>Memory limit</FieldLabel>
                  <FieldContent>
                    <Input
                      id={`service-${index}-limit-memory`}
                      value={service.deploy.resources.limits.memory || ""}
                      onChange={(e) =>
                        updateService({
                          deploy: {
                            ...service.deploy,
                            resources: {
                              ...service.deploy.resources,
                              limits: { ...service.deploy.resources.limits, memory: e.target.value },
                            },
                          },
                        })
                      }
                      placeholder="512M"
                    />
                    <FieldDescription>e.g. 512M, 1G</FieldDescription>
                  </FieldContent>
                </Field>
                <Field>
                  <FieldLabel htmlFor={`service-${index}-reserve-cpus`}>CPU reservation</FieldLabel>
                  <FieldContent>
                    <Input
                      id={`service-${index}-reserve-cpus`}
                      type="number"
                      step="0.1"
                      min="0"
                      value={service.deploy.resources.reservations.cpus || ""}
                      onChange={(e) =>
                        updateService({
                          deploy: {
                            ...service.deploy,
                            resources: {
                              ...service.deploy.resources,
                              reservations: { ...service.deploy.resources.reservations, cpus: e.target.value },
                            },
                          },
                        })
                      }
                      placeholder="0.5"
                    />
                    <FieldDescription>CPU cores</FieldDescription>
                  </FieldContent>
                </Field>
                <Field>
                  <FieldLabel htmlFor={`service-${index}-reserve-memory`}>Memory reservation</FieldLabel>
                  <FieldContent>
                    <Input
                      id={`service-${index}-reserve-memory`}
                      value={service.deploy.resources.reservations.memory || ""}
                      onChange={(e) =>
                        updateService({
                          deploy: {
                            ...service.deploy,
                            resources: {
                              ...service.deploy.resources,
                              reservations: { ...service.deploy.resources.reservations, memory: e.target.value },
                            },
                          },
                        })
                      }
                      placeholder="256M"
                    />
                    <FieldDescription>e.g. 256M</FieldDescription>
                  </FieldContent>
                </Field>
              </div>
            </FieldContent>
          </Field>

          <Separator />
          <Field>
            <FieldLabel htmlFor={`service-${index}-healthcheck`}>Health check</FieldLabel>
            <FieldContent>
              <div className="grid gap-4 md:grid-cols-2">
                <Field>
                  <FieldLabel htmlFor={`service-${index}-hc-test`}>Test command</FieldLabel>
                  <FieldContent>
                    <Input
                      id={`service-${index}-hc-test`}
                      value={service.healthcheck?.test || ""}
                      onChange={(e) =>
                        updateService({
                          healthcheck: {
                            ...service.healthcheck,
                            test: e.target.value,
                          } as HealthCheck,
                        })
                      }
                      placeholder="curl -f http://localhost/ || exit 1"
                    />
                  </FieldContent>
                </Field>
                <Field>
                  <FieldLabel htmlFor={`service-${index}-hc-interval`}>Interval</FieldLabel>
                  <FieldContent>
                    <Input
                      id={`service-${index}-hc-interval`}
                      value={service.healthcheck?.interval || ""}
                      onChange={(e) =>
                        updateService({
                          healthcheck: {
                            ...service.healthcheck,
                            interval: e.target.value,
                          } as HealthCheck,
                        })
                      }
                      placeholder="30s"
                    />
                  </FieldContent>
                </Field>
                <Field>
                  <FieldLabel htmlFor={`service-${index}-hc-timeout`}>Timeout</FieldLabel>
                  <FieldContent>
                    <Input
                      id={`service-${index}-hc-timeout`}
                      value={service.healthcheck?.timeout || ""}
                      onChange={(e) =>
                        updateService({
                          healthcheck: {
                            ...service.healthcheck,
                            timeout: e.target.value,
                          } as HealthCheck,
                        })
                      }
                      placeholder="10s"
                    />
                  </FieldContent>
                </Field>
                <Field>
                  <FieldLabel htmlFor={`service-${index}-hc-retries`}>Retries</FieldLabel>
                  <FieldContent>
                    <Input
                      id={`service-${index}-hc-retries`}
                      type="number"
                      min="0"
                      value={service.healthcheck?.retries || ""}
                      onChange={(e) =>
                        updateService({
                          healthcheck: {
                            ...service.healthcheck,
                            retries: parseInt(e.target.value) || 0,
                          } as HealthCheck,
                        })
                      }
                      placeholder="3"
                    />
                  </FieldContent>
                </Field>
              </div>
            </FieldContent>
          </Field>

          <Separator />
          <Field>
            <FieldLabel>Labels</FieldLabel>
            <FieldContent>
              <EditableTable<EnvVarWithId>
                items={service.labels.map((l, i) => ({ ...l, id: `label-${i}` }))}
                onChange={(items) => updateArrayField("labels", items)}
                addItem={() => ({ key: "", value: "", id: `label-${Date.now()}` })}
                columns={["Key", "Value"]}
                renderRow={(item, idx, moveUp, moveDown, remove) => (
                  <>
                    <TableCell>
                      <Input
                        placeholder="com.example.description"
                        value={item.key}
                        onChange={(e) =>
                          updateArrayItem("labels", idx, { ...item, key: e.target.value })
                        }
                      />
                    </TableCell>
                    <TableCell>
                      <Input
                        placeholder="My service"
                        value={item.value}
                        onChange={(e) =>
                          updateArrayItem("labels", idx, { ...item, value: e.target.value })
                        }
                      />
                    </TableCell>
                  </>
                )}
              />
            </FieldContent>
          </Field>

          <Separator />
          <FieldGroup>
            <Field>
              <FieldLabel>Networks</FieldLabel>
              <FieldContent>
                <Input
                  value={service.networks.join(", ")}
                  onChange={(e) => updateService({ networks: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
                  placeholder="backend, frontend"
                />
                <FieldDescription>Comma-separated network names. Define networks in the Networks tab.</FieldDescription>
              </FieldContent>
            </Field>
            <Field>
              <FieldLabel>Depends on</FieldLabel>
              <FieldContent>
                <Input
                  value={service.depends_on.join(", ")}
                  onChange={(e) => updateService({ depends_on: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
                  placeholder={allServiceNames.filter((n) => n !== service.name).join(", ")}
                />
                <FieldDescription>Comma-separated service names that must start before this one.</FieldDescription>
              </FieldContent>
            </Field>
          </FieldGroup>
        </div>
      )}
    </div>
  )
}

function NetworksTab({ form, onChange }: { form: ComposeFormData; onChange: (form: ComposeFormData) => void }) {
  const [networks, setNetworks] = React.useState<NetworkWithId[]>(
    Object.entries(form.networks).map(([name, config]) => ({
      name,
      driver: config.driver || "bridge",
      external: config.external || false,
      id: `net-${name}`,
    })),
  )

  React.useEffect(() => {
    onChange({
      ...form,
      networks: Object.fromEntries(networks.map((n) => [n.name, { driver: n.driver, external: n.external }])),
    })
  }, [networks, form, onChange])

  return (
    <TabsContent value="networks" className="pt-4">
      <EditableTable<NetworkWithId>
        items={networks}
        onChange={setNetworks}
        addItem={() => ({ name: "", driver: "bridge", external: false, id: `net-${Date.now()}` })}
        columns={["Name", "Driver", "External"]}
        renderRow={(item, idx, moveUp, moveDown, remove) => (
          <>
            <TableCell>
              <Input
                value={item.name}
                onChange={(e) => {
                  const next = [...networks]
                  const current = next[idx]
                  if (current) {
                    next[idx] = { ...current, name: e.target.value }
                    setNetworks(next)
                  }
                }}
                required
              />
            </TableCell>
            <TableCell>
              <Input value={item.driver} onChange={(e) => setNetworks(networks.map((n, i) => (i === idx ? { ...n, driver: e.target.value } : n)))} placeholder="bridge" />
            </TableCell>
            <TableCell>
              <Input
                type="checkbox"
                checked={item.external}
                onChange={(e) => setNetworks(networks.map((n, i) => (i === idx ? { ...n, external: e.target.checked } : n)))}
              />
            </TableCell>
          </>
        )}
      />
    </TabsContent>
  )
}

function VolumesTab({ form, onChange }: { form: ComposeFormData; onChange: (form: ComposeFormData) => void }) {
  const [volumes, setVolumes] = React.useState<VolumeWithId[]>(
    Object.entries(form.volumes).map(([name, config]) => ({
      name,
      driver: config.driver || "local",
      external: config.external || false,
      id: `vol-${name}`,
    })),
  )

  React.useEffect(() => {
    onChange({
      ...form,
      volumes: Object.fromEntries(volumes.map((v) => [v.name, { driver: v.driver, external: v.external }])),
    })
  }, [volumes, form, onChange])

  return (
    <TabsContent value="volumes" className="pt-4">
      <EditableTable<VolumeWithId>
        items={volumes}
        onChange={setVolumes}
        addItem={() => ({ name: "", driver: "local", external: false, id: `vol-${Date.now()}` })}
        columns={["Name", "Driver", "External"]}
        renderRow={(item, idx, moveUp, moveDown, remove) => (
          <>
            <TableCell>
              <Input
                value={item.name}
                onChange={(e) => setVolumes(volumes.map((v, i) => (i === idx ? { ...v, name: e.target.value } : v)))}
                required
              />
            </TableCell>
            <TableCell>
              <Input value={item.driver} onChange={(e) => setVolumes(volumes.map((v, i) => (i === idx ? { ...v, driver: e.target.value } : v)))} placeholder="local" />
            </TableCell>
            <TableCell>
              <Input
                type="checkbox"
                checked={item.external}
                onChange={(e) => setVolumes(volumes.map((v, i) => (i === idx ? { ...v, external: e.target.checked } : v)))}
              />
            </TableCell>
          </>
        )}
      />
    </TabsContent>
  )
}

interface ComposeFormProps {
  value: string
  onChange: (value: string) => void
  ariaLabel?: string
  minHeight?: string
  showRawTab?: boolean
}

export function ComposeForm({ value, onChange, ariaLabel = "compose.yaml", minHeight = "20rem", showRawTab = true }: ComposeFormProps) {
  const [form, setForm] = React.useState<ComposeFormData>(() => parseComposeToForm(value))
  const [activeTab, setActiveTab] = React.useState<"form" | "raw" | "networks" | "volumes">("form")
  const [validationError, setValidationError] = React.useState<string | null>(null)

  const serviceNames = React.useMemo(() => Object.keys(form.services), [form.services])
  const allServiceNames = serviceNames

  const serialize = React.useCallback(() => {
    try {
      const yaml = serializeFormToCompose(form)
      setValidationError(null)
      onChange(yaml)
      return yaml
    } catch (e) {
      setValidationError(e instanceof Error ? e.message : "Serialization failed")
      return value
    }
  }, [form, onChange, value])

  React.useEffect(() => {
    serialize()
  }, [serialize])

  React.useEffect(() => {
    if (activeTab !== "form") return
    try {
      const parsed = parseComposeToForm(value)
      if (Object.keys(parsed.services).length > 0 || Object.keys(parsed.networks).length > 0 || Object.keys(parsed.volumes).length > 0) {
        setForm(parsed)
      }
    } catch {
      // Ignore parse errors, keep current form
    }
  }, [value, activeTab])

  const handleFormChange = (newForm: ComposeFormData) => {
    setForm(newForm)
  }

  const addService = () => {
    const newName = `service${serviceNames.length + 1}`
    handleFormChange({
      ...form,
      services: { ...form.services, [newName]: { ...DEFAULT_SERVICE, name: newName } },
    })
  }

  return (
    <div className="flex flex-col h-full min-h-[20rem]">
      <Tabs value={activeTab} onValueChange={setActiveTab as any} className="flex flex-col h-full">
        <TabsList>
          <TabsTrigger value="form">Form</TabsTrigger>
          <TabsTrigger value="networks">Networks</TabsTrigger>
          <TabsTrigger value="volumes">Volumes</TabsTrigger>
          {showRawTab && <TabsTrigger value="raw">Raw YAML</TabsTrigger>}
        </TabsList>

        <TabsContent value="form" className="flex-1 overflow-auto p-4 space-y-6 min-h-0">
          {validationError && (
            <div className="rounded-md bg-destructive/10 border border-destructive/20 p-3 text-sm text-destructive">
              {validationError}
            </div>
          )}

          <div className="space-y-4">
            {Object.entries(form.services).map(([name, svc], index) => (
              <ServiceFormComponent
                key={name}
                service={svc}
                index={index}
                serviceNames={serviceNames}
                allServiceNames={allServiceNames}
                onChange={(updated) =>
                  handleFormChange({
                    ...form,
                    services: { ...form.services, [name]: updated },
                  })
                }
              />
            ))}
          </div>

          <Button variant="outline" onClick={addService}>
            <PlusIcon className="h-4 w-4 mr-2" />
            Add service
          </Button>
        </TabsContent>

        <NetworksTab form={form} onChange={handleFormChange} />
        <VolumesTab form={form} onChange={handleFormChange} />

        {showRawTab && (
          <TabsContent value="raw" className="flex-1 min-h-0">
            <CodeEditor
              value={value}
              onChange={onChange}
              aria-label={ariaLabel}
              minHeight={minHeight}
              language="yaml"
            />
          </TabsContent>
        )}
      </Tabs>
    </div>
  )
}