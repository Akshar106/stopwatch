output "budget_names" {
  description = "Budget names keyed by kind (actual, forecast)."
  value       = { for k, b in aws_budgets_budget.this : k => b.name }
}
