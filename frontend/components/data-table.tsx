"use client"

import * as React from "react"
import {
  IconChevronDown,
  IconChevronLeft,
  IconChevronRight,
  IconChevronsLeft,
  IconChevronsRight,
  IconCircleCheckFilled,
  IconClock,
  IconDotsVertical,
  IconLayoutColumns,
  IconLoader,
  IconPlus,
} from "@tabler/icons-react"
import {
  columnFilteringFeature,
  columnVisibilityFeature,
  createColumnHelper,
  createFilteredRowModel,
  createPaginatedRowModel,
  createSortedRowModel,
  FlexRender,
  rowPaginationFeature,
  rowSelectionFeature,
  rowSortingFeature,
  tableFeatures,
  useTable,
  type ColumnFiltersState,
  type ColumnVisibilityState,
  type SortingState,
} from "@tanstack/react-table"
import { toast } from "sonner"
import { z } from "zod"

import { useIsMobile } from "@/hooks/use-mobile"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Drawer,
  DrawerClose,
  DrawerContent,
  DrawerDescription,
  DrawerFooter,
  DrawerHeader,
  DrawerTitle,
  DrawerTrigger,
} from "@/components/ui/drawer"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs"
import { useCases, useCreateCase } from "@/lib/hooks"
import type { Case } from "@/lib/api"

const features = tableFeatures({
  columnFilteringFeature,
  columnVisibilityFeature,
  rowPaginationFeature,
  rowSelectionFeature,
  rowSortingFeature,
  filteredRowModel: createFilteredRowModel(),
  paginatedRowModel: createPaginatedRowModel(),
  sortedRowModel: createSortedRowModel(),
})

const columnHelper = createColumnHelper<typeof features, Case>()

const statusVariant = (status: string) => {
  if (status === "open") return "default"
  if (status === "under_review") return "secondary"
  return "outline"
}

const columns = columnHelper.columns([
  columnHelper.display({
    id: "select",
    header: ({ table }) => (
      <div className="flex items-center justify-center">
        <Checkbox
          checked={table.getIsAllPageRowsSelected() || (table.getIsSomePageRowsSelected() && "indeterminate")}
          onCheckedChange={(value) => table.toggleAllPageRowsSelected(!!value)}
          aria-label="Select all"
        />
      </div>
    ),
    cell: ({ row }) => (
      <div className="flex items-center justify-center">
        <Checkbox
          checked={row.getIsSelected()}
          onCheckedChange={(value) => row.toggleSelected(!!value)}
          aria-label="Select row"
        />
      </div>
    ),
    enableSorting: false,
    enableHiding: false,
  }),
  columnHelper.accessor("title", {
    header: "Case Title",
    cell: ({ row }) => <CaseDrawer item={row.original} />,
    enableHiding: false,
  }),
  columnHelper.accessor("status", {
    header: "Status",
    cell: ({ row }) => (
      <Badge variant={statusVariant(row.original.status)} className="px-1.5 capitalize">
        {row.original.status === "open" ? (
          <IconCircleCheckFilled className="fill-green-500 dark:fill-green-400 mr-1" />
        ) : row.original.status === "under_review" ? (
          <IconLoader className="mr-1" />
        ) : null}
        {row.original.status.replace("_", " ")}
      </Badge>
    ),
  }),
  columnHelper.accessor("description", {
    header: "Description",
    cell: ({ row }) => (
      <span className="max-w-[200px] truncate text-muted-foreground text-sm block">
        {row.original.description || "—"}
      </span>
    ),
  }),
  columnHelper.accessor("created_at", {
    header: "Created",
    cell: ({ row }) => (
      <span className="text-sm text-muted-foreground whitespace-nowrap">
        {new Date(row.original.created_at).toLocaleDateString()}
      </span>
    ),
  }),
  columnHelper.display({
    id: "actions",
    cell: ({ row }) => (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            className="flex size-8 text-muted-foreground data-[state=open]:bg-muted"
            size="icon"
          >
            <IconDotsVertical />
            <span className="sr-only">Open menu</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-32">
          <DropdownMenuItem onClick={() => window.location.href = `/dashboard?case=${row.original.id}`}>
            Investigate
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem variant="destructive">Delete</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    ),
  }),
])

function NewCaseDialog() {
  const [open, setOpen] = React.useState(false)
  const [title, setTitle] = React.useState("")
  const [description, setDescription] = React.useState("")
  const createCase = useCreateCase()
  const isMobile = useIsMobile()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim()) return
    try {
      await createCase.mutateAsync({ title: title.trim(), description: description.trim() || undefined })
      toast.success("Case created successfully")
      setTitle("")
      setDescription("")
      setOpen(false)
    } catch {
      toast.error("Failed to create case")
    }
  }

  return (
    <Drawer open={open} onOpenChange={setOpen} direction={isMobile ? "bottom" : "right"}>
      <DrawerTrigger asChild>
        <Button variant="outline" size="sm">
          <IconPlus />
          <span className="hidden lg:inline">New Case</span>
        </Button>
      </DrawerTrigger>
      <DrawerContent>
        <DrawerHeader className="gap-1">
          <DrawerTitle>Create new case</DrawerTitle>
          <DrawerDescription>Open a new investigation case for blockchain tracing.</DrawerDescription>
        </DrawerHeader>
        <div className="px-4">
          <form id="new-case-form" onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="case-title">Case title</Label>
              <Input
                id="case-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="LEA-2026-XXXX"
                required
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="case-desc">Description (optional)</Label>
              <Input
                id="case-desc"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Brief description of the incident"
              />
            </div>
          </form>
        </div>
        <DrawerFooter>
          <Button form="new-case-form" type="submit" disabled={createCase.isPending}>
            {createCase.isPending ? "Creating..." : "Create case"}
          </Button>
          <DrawerClose asChild>
            <Button variant="outline">Cancel</Button>
          </DrawerClose>
        </DrawerFooter>
      </DrawerContent>
    </Drawer>
  )
}

function CaseDrawer({ item }: { item: Case }) {
  const isMobile = useIsMobile()
  return (
    <Drawer direction={isMobile ? "bottom" : "right"}>
      <DrawerTrigger asChild>
        <Button variant="link" className="w-fit px-0 text-left text-foreground">
          {item.title}
        </Button>
      </DrawerTrigger>
      <DrawerContent>
        <DrawerHeader className="gap-1">
          <DrawerTitle>{item.title}</DrawerTitle>
          <DrawerDescription>Case ID: {item.id}</DrawerDescription>
        </DrawerHeader>
        <div className="flex flex-col gap-4 overflow-y-auto px-4 text-sm">
          <div className="grid gap-3">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Status</span>
              <Badge variant={statusVariant(item.status)} className="capitalize">
                {item.status.replace("_", " ")}
              </Badge>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Created</span>
              <span>{new Date(item.created_at).toLocaleDateString()}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Updated</span>
              <span>{new Date(item.updated_at).toLocaleDateString()}</span>
            </div>
            {item.description && (
              <div className="flex flex-col gap-1">
                <span className="text-muted-foreground">Description</span>
                <p>{item.description}</p>
              </div>
            )}
          </div>
        </div>
        <DrawerFooter>
          <Button onClick={() => window.location.href = `/dashboard?case=${item.id}`}>
            Open Investigation
          </Button>
          <DrawerClose asChild>
            <Button variant="outline">Close</Button>
          </DrawerClose>
        </DrawerFooter>
      </DrawerContent>
    </Drawer>
  )
}

export function DataTable() {
  const [page, setPage] = React.useState(1)
  const [pageSize, setPageSize] = React.useState(10)
  const [statusFilter, setStatusFilter] = React.useState<string | undefined>()
  const [searchQuery, setSearchQuery] = React.useState("")
  const [debouncedQuery, setDebouncedQuery] = React.useState("")

  // Debounce search
  React.useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(searchQuery), 400)
    return () => clearTimeout(t)
  }, [searchQuery])

  const { data, isLoading } = useCases({
    page,
    page_size: pageSize,
    status: statusFilter,
    q: debouncedQuery || undefined,
  })

  const cases = data?.items ?? []
  const total = data?.total ?? 0

  const [rowSelection, setRowSelection] = React.useState({})
  const [columnVisibility, setColumnVisibility] = React.useState<ColumnVisibilityState>({})
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([])
  const [sorting, setSorting] = React.useState<SortingState>([])
  const [pagination, setPagination] = React.useState({ pageIndex: 0, pageSize })

  const table = useTable({
    features,
    data: cases,
    columns,
    state: { sorting, columnVisibility, rowSelection, columnFilters, pagination },
    getRowId: (row) => row.id,
    enableRowSelection: true,
    manualPagination: true,
    rowCount: total,
    onRowSelectionChange: setRowSelection,
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onColumnVisibilityChange: setColumnVisibility,
    onPaginationChange: (updater) => {
      const next = typeof updater === "function" ? updater(pagination) : updater
      setPagination(next)
      setPage(next.pageIndex + 1)
      setPageSize(next.pageSize)
    },
  })

  return (
    <Tabs defaultValue="outline" className="w-full flex-col justify-start gap-6">
      <div className="flex items-center justify-between px-4 lg:px-6">
        <div className="flex items-center gap-2">
          <Input
            placeholder="Search cases..."
            value={searchQuery}
            onChange={(e) => { setSearchQuery(e.target.value); setPage(1) }}
            className="h-8 w-48"
          />
          <Select
            value={statusFilter ?? "all"}
            onValueChange={(v) => { setStatusFilter(v === "all" ? undefined : v); setPage(1) }}
          >
            <SelectTrigger size="sm" className="w-36">
              <SelectValue placeholder="All statuses" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="open">Open</SelectItem>
              <SelectItem value="under_review">Under review</SelectItem>
              <SelectItem value="closed">Closed</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="flex items-center gap-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm">
                <IconLayoutColumns />
                <span className="hidden lg:inline">Columns</span>
                <IconChevronDown />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-44">
              {table
                .getAllColumns()
                .filter((col) => typeof col.accessorFn !== "undefined" && col.getCanHide())
                .map((col) => (
                  <DropdownMenuCheckboxItem
                    key={col.id}
                    className="capitalize"
                    checked={col.getIsVisible()}
                    onCheckedChange={(v) => col.toggleVisibility(!!v)}
                  >
                    {col.id}
                  </DropdownMenuCheckboxItem>
                ))}
            </DropdownMenuContent>
          </DropdownMenu>
          <NewCaseDialog />
        </div>
      </div>

      <TabsContent value="outline" className="relative flex flex-col gap-4 overflow-auto px-4 lg:px-6">
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader className="sticky top-0 z-10 bg-muted">
              {table.getHeaderGroups().map((hg) => (
                <TableRow key={hg.id}>
                  {hg.headers.map((h) => (
                    <TableHead key={h.id} colSpan={h.colSpan}>
                      {h.isPlaceholder ? null : <FlexRender header={h} />}
                    </TableHead>
                  ))}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {isLoading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <TableRow key={i}>
                    {columns.map((_, j) => (
                      <TableCell key={j}>
                        <div className="h-4 w-full animate-pulse rounded bg-muted" />
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              ) : table.getRowModel().rows.length ? (
                table.getRowModel().rows.map((row) => (
                  <TableRow key={row.id} data-state={row.getIsSelected() && "selected"}>
                    {row.getVisibleCells().map((cell) => (
                      <TableCell key={cell.id}>
                        <FlexRender cell={cell} />
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={columns.length} className="h-24 text-center">
                    No cases found.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>

        <div className="flex items-center justify-between px-4">
          <div className="hidden flex-1 text-sm text-muted-foreground lg:flex">
            {table.getFilteredSelectedRowModel().rows.length} of {total} case(s)
          </div>
          <div className="flex w-full items-center gap-8 lg:w-fit">
            <div className="hidden items-center gap-2 lg:flex">
              <Label htmlFor="rows-per-page" className="text-sm font-medium">Rows per page</Label>
              <Select
                value={`${pagination.pageSize}`}
                onValueChange={(v) => { table.setPageSize(Number(v)); setPage(1) }}
              >
                <SelectTrigger size="sm" className="w-20" id="rows-per-page">
                  <SelectValue placeholder={pagination.pageSize} />
                </SelectTrigger>
                <SelectContent side="top">
                  {[10, 20, 30, 50].map((s) => (
                    <SelectItem key={s} value={`${s}`}>{s}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex w-fit items-center justify-center text-sm font-medium">
              Page {pagination.pageIndex + 1} of {table.getPageCount()}
            </div>
            <div className="ml-auto flex items-center gap-2 lg:ml-0">
              <Button variant="outline" className="hidden h-8 w-8 p-0 lg:flex" onClick={() => table.setPageIndex(0)} disabled={!table.getCanPreviousPage()}>
                <IconChevronsLeft />
              </Button>
              <Button variant="outline" className="size-8" size="icon" onClick={() => table.previousPage()} disabled={!table.getCanPreviousPage()}>
                <IconChevronLeft />
              </Button>
              <Button variant="outline" className="size-8" size="icon" onClick={() => table.nextPage()} disabled={!table.getCanNextPage()}>
                <IconChevronRight />
              </Button>
              <Button variant="outline" className="hidden size-8 lg:flex" size="icon" onClick={() => table.setPageIndex(table.getPageCount() - 1)} disabled={!table.getCanNextPage()}>
                <IconChevronsRight />
              </Button>
            </div>
          </div>
        </div>
      </TabsContent>
    </Tabs>
  )
}
