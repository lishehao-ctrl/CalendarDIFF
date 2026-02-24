import { FormEventHandler } from "react";
import { Loader2 } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { SourceOverrides } from "@/lib/types";
import { TaskChoice } from "@/lib/hooks/use-dashboard-data";

type ManagementSectionProps = {
  scopedError: string | null;
  scopedLoading: boolean;

  overrides: SourceOverrides;

  courseSet: string[];
  courseOriginal: string;
  courseDisplay: string;
  courseBusy: boolean;
  onCourseOriginalChange: (value: string) => void;
  onCourseDisplayChange: (value: string) => void;
  onSaveCourseRename: FormEventHandler<HTMLFormElement>;
  onDeleteCourseRename: (originalLabel: string) => void | Promise<void>;
  formatCourseOptionLabel: (label: string) => string;

  taskSet: TaskChoice[];
  taskUid: string;
  taskDisplayTitle: string;
  taskBusy: boolean;
  onTaskUidChange: (value: string) => void;
  onTaskDisplayTitleChange: (value: string) => void;
  onSaveTaskRename: FormEventHandler<HTMLFormElement>;
  onDeleteTaskRename: (uid: string) => void | Promise<void>;
  getTaskDisplayTitle: (uid: string, title: string) => string;
};

export function ManagementSection({
  scopedError,
  scopedLoading,
  overrides,
  courseSet,
  courseOriginal,
  courseDisplay,
  courseBusy,
  onCourseOriginalChange,
  onCourseDisplayChange,
  onSaveCourseRename,
  onDeleteCourseRename,
  formatCourseOptionLabel,
  taskSet,
  taskUid,
  taskDisplayTitle,
  taskBusy,
  onTaskUidChange,
  onTaskDisplayTitleChange,
  onSaveTaskRename,
  onDeleteTaskRename,
  getTaskDisplayTitle,
}: ManagementSectionProps) {
  return (
    <section id="management" className="section-anchor">
      <div className="grid gap-4 xl:grid-cols-2">
        <Card className="animate-fade-in">
          <CardHeader>
            <CardTitle>Management: Course Rename</CardTitle>
            <CardDescription>Override course display label for clearer UI and review context.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {scopedError ? (
              <Alert>
                <AlertTitle>Scoped Data Failed</AlertTitle>
                <AlertDescription>{scopedError}</AlertDescription>
              </Alert>
            ) : scopedLoading ? (
              <div className="space-y-2">
                <Skeleton className="h-10" />
                <Skeleton className="h-10" />
                <Skeleton className="h-24" />
              </div>
            ) : (
              <>
                <form className="space-y-3" onSubmit={onSaveCourseRename}>
                  <div className="space-y-2">
                    <Label htmlFor="course-original">Original Course</Label>
                    <Select
                      id="course-original"
                      value={courseOriginal}
                      onChange={(event) => onCourseOriginalChange(event.target.value)}
                      disabled={!courseSet.length}
                    >
                      {courseSet.map((label) => (
                        <option key={label} value={label}>
                          {formatCourseOptionLabel(label)}
                        </option>
                      ))}
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="course-display">Display Name</Label>
                    <Input
                      id="course-display"
                      value={courseDisplay}
                      onChange={(event) => onCourseDisplayChange(event.target.value)}
                      maxLength={64}
                      required
                    />
                  </div>
                  <Button type="submit" disabled={courseBusy || !courseOriginal}>
                    {courseBusy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                    Save Course Rename
                  </Button>
                </form>

                <div className="space-y-2">
                  {overrides.courses.length ? (
                    overrides.courses.map((item) => (
                      <div
                        key={item.id}
                        className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-line bg-slate-50 px-3 py-2"
                      >
                        <div className="text-sm text-ink">
                          <span className="font-semibold">{item.original_course_label}</span> -&gt; {item.display_course_label}
                        </div>
                        <Button variant="danger" size="sm" onClick={() => void onDeleteCourseRename(item.original_course_label)}>
                          Delete
                        </Button>
                      </div>
                    ))
                  ) : (
                    <p className="text-sm text-muted">No course overrides configured.</p>
                  )}
                </div>
              </>
            )}
          </CardContent>
        </Card>

        <Card className="animate-fade-in">
          <CardHeader>
            <CardTitle>Management: Task Rename</CardTitle>
            <CardDescription>Map raw event UID titles to user-facing labels.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {scopedError ? (
              <Alert>
                <AlertTitle>Scoped Data Failed</AlertTitle>
                <AlertDescription>{scopedError}</AlertDescription>
              </Alert>
            ) : scopedLoading ? (
              <div className="space-y-2">
                <Skeleton className="h-10" />
                <Skeleton className="h-10" />
                <Skeleton className="h-24" />
              </div>
            ) : (
              <>
                <form className="space-y-3" onSubmit={onSaveTaskRename}>
                  <div className="space-y-2">
                    <Label htmlFor="task-uid">Task UID</Label>
                    <Select
                      id="task-uid"
                      value={taskUid}
                      onChange={(event) => onTaskUidChange(event.target.value)}
                      disabled={!taskSet.length}
                    >
                      {taskSet.map((item) => (
                        <option key={item.uid} value={item.uid}>
                          {item.uid} - {getTaskDisplayTitle(item.uid, item.title)}
                        </option>
                      ))}
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="task-display">Display Title</Label>
                    <Input
                      id="task-display"
                      value={taskDisplayTitle}
                      onChange={(event) => onTaskDisplayTitleChange(event.target.value)}
                      maxLength={512}
                      required
                    />
                  </div>
                  <Button type="submit" disabled={taskBusy || !taskUid}>
                    {taskBusy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                    Save Task Rename
                  </Button>
                </form>

                <div className="space-y-2">
                  {overrides.tasks.length ? (
                    overrides.tasks.map((item) => (
                      <div
                        key={item.id}
                        className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-line bg-slate-50 px-3 py-2"
                      >
                        <div className="text-sm text-ink">
                          <span className="font-semibold">{item.event_uid}</span> -&gt; {item.display_title}
                        </div>
                        <Button variant="danger" size="sm" onClick={() => void onDeleteTaskRename(item.event_uid)}>
                          Delete
                        </Button>
                      </div>
                    ))
                  ) : (
                    <p className="text-sm text-muted">No task overrides configured.</p>
                  )}
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </section>
  );
}
