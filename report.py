# Phase IV: loads job_tracker.csv, generates charts and follow-up CSV

import pandas as pd
import plotly.graph_objects as go
from patterns import assign_role

STATUS_ORDER = ['Applied', 'Interview', 'Assessment', 'Offer', 'Rejected']


if __name__ == '__main__':
    # Load once and derive all views from the same DataFrame
    df = pd.read_csv('job_tracker.csv')
    # utc=True guarantees a tz-aware column, so tz_convert(None) can't raise on tz-naive input
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce', utc=True).dt.tz_convert(None)
    df['Role'] = assign_role(df.get('JobTitle', pd.Series(dtype=str)))

    today = pd.Timestamp.now()

    # --- Follow-up engine ---
    applied = df[df['Status'] == 'Applied'].copy()
    applied['days_since'] = (today - applied['Date']).dt.days
    applied = applied[(applied['days_since'] >= 7) & (applied['days_since'] <= 90)]
    applied['days_since_bucket'] = pd.cut(
        applied['days_since'],
        bins=[0, 7, 14, 21, 90],
        labels=['1-7', '8-14', '15-21', '22-90']
    )
    print(applied[['Company', 'JobTitle', 'Date', 'days_since', 'days_since_bucket']].sort_values('days_since', ascending=False))

    followup_cols = [c for c in ['Company', 'JobTitle', 'Date', 'days_since', 'days_since_bucket', 'MsgId'] if c in applied.columns]
    applied[followup_cols].sort_values('days_since', ascending=False).to_csv('followup_needed.csv', index=False)
    print('Follow-up list saved to followup_needed.csv')

    # --- Analytics ---
    any_response = df['Status'].isin(['Interview', 'Offer', 'Rejected']).sum()
    response_rate = any_response / len(df) if len(df) > 0 else 0
    print(f'\nAny response rate: {response_rate:.2%}')
    print(df['Status'].value_counts())
    print(df.groupby(df['Date'].dt.to_period('M')).size())
    print(df['Role'].value_counts())

    # --- Visuals ---
    role_counts = df['Role'].value_counts()
    fig_roles = go.Figure(data=[go.Bar(
        x=role_counts.index, y=role_counts.values,
        text=role_counts.values, textposition='auto'
    )])
    fig_roles.update_layout(title='Applications by Role Cluster', xaxis_title='Role', yaxis_title='Count')

    status_counts = df['Status'].value_counts().reindex(STATUS_ORDER).dropna()
    fig_funnel = go.Figure(data=[go.Funnel(
        y=status_counts.index, x=status_counts.values, textinfo='value+percent initial'
    )])
    fig_funnel.update_layout(title='Application Funnel')

    applications_by_month = df.groupby(df['Date'].dt.to_period('M')).size()
    fig_months = go.Figure(data=[go.Scatter(
        x=applications_by_month.index.astype(str), y=applications_by_month.values,
        mode='lines+markers', hovertemplate='%{x}: %{y} applications<extra></extra>'
    )])
    fig_months.update_layout(title='Applications by Month', xaxis_title='Month', yaxis_title='Count')

    fig_roles.write_html('report_roles.html')
    fig_funnel.write_html('report_funnel.html')
    fig_months.write_html('report_months.html')
    # PNG export requires: pip install kaleido==0.2.1
    # fig_roles.write_image('report_roles.png')
    # fig_funnel.write_image('report_funnel.png')
    # fig_months.write_image('report_months.png')
    print('Charts saved: report_roles.html, report_funnel.html, report_months.html')
