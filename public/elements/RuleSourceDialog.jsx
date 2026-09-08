import React, { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function RuleSourceDialog() {
  const [values, setValues] = useState({
    rule_source_product: props.rule_source_product || "",
    rule_source_log_vendor: props.rule_source_log_vendor || "",
    rule_source_data_source: props.rule_source_data_source || "",
  });
  const [timeLeft, setTimeLeft] = useState(props.timeout_seconds || 300);
  const [submitting, setSubmitting] = useState(false);
  const [open, setOpen] = useState(true);

  const valid = useMemo(
    () =>
      values.rule_source_product.trim().length > 0 &&
      values.rule_source_log_vendor.trim().length > 0,
    [values],
  );

  const updateValue = (key, value) => {
    setValues((current) => ({ ...current, [key]: value }));
  };

  const finish = async (name, payload, closeImmediately = false) => {
    if (submitting) return;
    setSubmitting(true);
    try {
      if (closeImmediately) {
        setOpen(false);
        await deleteElement();
      }
      const result = await callAction({ name, payload });
      if (!result?.success) throw new Error("action failed");
      if (!closeImmediately) await deleteElement();
    } catch {
      setSubmitting(false);
      toast.error("操作提交失败，请重试");
    }
  };

  const cancel = (reason = "cancel") =>
    finish("cancel_rule_source_fields", { reason });

  const submit = () => {
    if (!valid) return;
    return finish(
      "submit_rule_source_fields",
      {
        rule_source_product: values.rule_source_product.trim(),
        rule_source_log_vendor: values.rule_source_log_vendor.trim(),
        rule_source_data_source: values.rule_source_data_source.trim(),
      },
      true,
    );
  };

  useEffect(() => {
    if (timeLeft <= 0) {
      cancel("timeout");
      return;
    }
    const timer = window.setTimeout(
      () => setTimeLeft((current) => current - 1),
      1000,
    );
    return () => window.clearTimeout(timer);
  }, [timeLeft]);

  return (
    <Dialog open={open} onOpenChange={(open) => !open && cancel()}>
      <DialogContent id="rule-source-dialog" className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>填写数据源信息</DialogTitle>
          <DialogDescription>
            用于入口规则固定字段，以及入口规则和子规则的厂商、产品命名。
            表单将在 {timeLeft} 秒后自动取消。
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-2">
          <div className="grid gap-2">
            <Label htmlFor="rule-source-product">
              数据源产品 <span className="text-destructive">*</span>
            </Label>
            <Input
              id="rule-source-product"
              autoFocus
              value={values.rule_source_product}
              placeholder="例如：WAF"
              onChange={(event) =>
                updateValue("rule_source_product", event.target.value)
              }
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="rule-source-vendor">
              数据源厂商 <span className="text-destructive">*</span>
            </Label>
            <Input
              id="rule-source-vendor"
              value={values.rule_source_log_vendor}
              placeholder="例如：绿盟"
              onChange={(event) =>
                updateValue("rule_source_log_vendor", event.target.value)
              }
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="rule-source-name">数据源（可选）</Label>
            <Input
              id="rule-source-name"
              value={values.rule_source_data_source}
              placeholder="留空则自动生成：数据源产品(数据源厂商)"
              onChange={(event) =>
                updateValue("rule_source_data_source", event.target.value)
              }
            />
          </div>
        </div>

        <DialogFooter>
          <Button
            id="rule-source-cancel"
            type="button"
            variant="outline"
            disabled={submitting}
            onClick={() => cancel()}
          >
            取消
          </Button>
          <Button
            id="rule-source-submit"
            type="button"
            disabled={!valid || submitting}
            onClick={submit}
          >
            确认并继续
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
