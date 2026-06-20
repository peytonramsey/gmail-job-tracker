# Phase IV: loads job_tracker.csv, generates charts + markdown report

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import timedelta

## Follow-up engine
job_emails = pd.read_csv('job_tracker.csv')

# keep only rows where status == 'Applied'
job_emails = job_emails[job_emails['Status'] == 'Applied']

# calculate days_since = today - Date
job_emails['Date'] = pd.to_datetime(job_emails['Date'])
job_emails['Date'] = job_emails['Date'].dt.tz_convert(None)
now = pd.Timestamp.now()

job_emails['days_since'] = (now - job_emails['Date']).dt.days

# bucket into 7, 14, 21 day intervals; drop anything over 90 days
job_emails = job_emails[(job_emails['days_since'] >= 7) & (job_emails['days_since'] <= 90)]
job_emails['days_since_bucket'] = pd.cut(job_emails['days_since'], bins=[0, 7, 14, 21, 90], labels=['1-7', '8-14', '15-21', '22-90'])

print(job_emails[['Company', 'JobTitle', 'Date', 'days_since', 'days_since_bucket']].sort_values('days_since', ascending=False))

## Analytics
df = pd.read_csv('job_tracker.csv')
df['Date'] = pd.to_datetime(df['Date']).dt.tz_convert(None)

any_response_rate = df['Status'].isin(['Interview', 'Offer', 'Rejected']).sum() / len(df)
print(f'Any response rate: {any_response_rate:.2%}')

funnel = df['Status'].value_counts()
print(funnel)

applications_by_month = df.groupby(df['Date'].dt.to_period('M')).size()
print(applications_by_month)

## Role clustering
title = df['JobTitle'].str.lower().fillna('')

conditions = [
    title.str.contains('data scientist|machine learning|ml engineer|ai engineer|research scientist', na=False),
    title.str.contains('software engineer|backend|frontend|full.?stack|developer', na=False),
    title.str.contains('data analyst|analytics engineer|business analyst|quantitative', na=False),
    title.str.contains('product manager|product analyst', na=False),
    title.str.contains('data engineer|platform engineer|cloud engineer|devops', na=False),
]
choices = ['Data Science / ML', 'Software Engineering', 'Analytics', 'Product', 'Data Engineering']

df['Role'] = np.select(conditions, choices, default='Other')
print(df['Role'].value_counts())

## Visuals
# Bar chart: applications by role cluster
role_counts = df['Role'].value_counts()
fig_roles = go.Figure(data=[go.Bar(
    x=role_counts.index,
    y=role_counts.values,
    text=role_counts.values,
    textposition='auto'
)])
fig_roles.update_layout(title='Applications by Role Cluster', xaxis_title='Role', yaxis_title='Count')

# Funnel chart: status progression (Applied -> Interview -> Offer)
status_order = ['Applied', 'Interview', 'Assessment', 'Offer', 'Rejected']
status_counts = df['Status'].value_counts().reindex(status_order).dropna()
fig_funnel = go.Figure(data=[go.Funnel(
    y=status_counts.index,
    x=status_counts.values,
    textinfo='value+percent initial'
)])
fig_funnel.update_layout(title='Application Funnel')

# Line chart: applications submitted per month
applications_by_month = df.groupby(df['Date'].dt.to_period('M')).size()
fig_months = go.Figure(data=[go.Scatter(
    x=applications_by_month.index.astype(str),
    y=applications_by_month.values,
    mode='lines+markers',
    hovertemplate='%{x}: %{y} applications<extra></extra>'
)])
fig_months.update_layout(title='Applications by Month', xaxis_title='Month', yaxis_title='Count')

fig_roles.write_html('report_roles.html')
fig_funnel.write_html('report_funnel.html')
fig_months.write_html('report_months.html')
print('Charts saved: report_roles.html, report_funnel.html, report_months.html')

## Markdown weekly report
today = pd.Timestamp.now()
week_ago = today - timedelta(days=7)

total        = len(df)
this_week    = (df['Date'] >= week_ago).sum()
interviews   = (df['Status'] == 'Interview').sum()
offers       = (df['Status'] == 'Offer').sum()
rejected     = (df['Status'] == 'Rejected').sum()
pending      = (df['Status'] == 'Applied').sum()
any_response = df['Status'].isin(['Interview', 'Offer', 'Rejected']).sum()
response_rate = any_response / total if total > 0 else 0
overdue      = ((df['Status'] == 'Applied') & ((today - df['Date']).dt.days >= 14)).sum()

report = f"""
# Job Search Report: {today.strftime('%B %d, %Y')}

## This Week
- Applications sent: **{this_week}**

## Overall Pipeline
| Stage | Count |
|---|---|
| Total applications | {total} |
| Interviews | {interviews} |
| Offers | {offers} |
| Rejections | {rejected} |
| Pending (no reply) | {pending} |

**Response rate: {response_rate:.1%}**

## Needs Attention
- {overdue} applications with no reply in 14+ days
"""

print(report)
