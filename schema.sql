-- USAGE: sqlite3 /tmp/finance.db < schema.sql

-- set up and load main tables

.separator ","

drop table if exists buckets;
create table buckets (
  bucketid integer primary key autoincrement,
  bucketname string not null,
  buckettype string not null,
  initialbalancecents integer
);

.import buckets_starter.csv buckets

drop table if exists entries;
create table entries (
  entryid integer primary key autoincrement,
  description string not null,
  amountcents integer,
  srcbucket integer,
  destbucket integer
);

.import entries_starter.csv entries

drop table if exists proportions;
create table proportions (
  proportionid integer not null,
  proportionbucketid integer not null,
  percent integer not null
);

.import proportions_starter.csv proportions

-- create views

drop view if exists entries_labeled;
create view entries_labeled as
select entryid, description, amountcents, src.bucketid as srcbucketid, src.bucketname as srcbucketname, src.buckettype as srcbuckettype, dest.bucketid as destbucketid, dest.bucketname as destbucketname, dest.buckettype as destbuckettype
from entries
  join buckets as src
    on entries.srcbucket = src.bucketid
  join buckets as dest
    on entries.destbucket = dest.bucketid
  order by entryid asc;

drop view if exists proportions_labeled;
create view proportions_labeled as
select proportionid, p.bucketname as proportionname, proportionbucketid, b.bucketname as bucketname, b.buckettype as buckettype, percent
from proportions
  join buckets as p
    on proportions.proportionid = p.bucketid
  join buckets as b
    on proportions.proportionbucketid = b.bucketid;

drop view if exists double_entries;
create view double_entries as 
select entryid, description, amountcents, destbucket as bucket from entries
  union
select entryid, description, -amountcents as amountcents, srcbucket as bucket from entries;

drop view if exists double_entries_labeled;
create view double_entries_labeled as
select
  entryid, description, amountcents, bucketid, bucketname, buckettype
from double_entries
  join buckets
    on bucket = bucketid;

drop view if exists double_entries_labeled_expand_proportions;
create view double_entries_labeled_expand_proportions as
select
    entryid,
    description,
    --cast(round(amountcents * percent / 100.0) as integer) as amountcents,
    amountcents * percent / 100.0 as amountcents,
    p.proportionbucketid as bucketid,
    p.bucketname as bucketname,
    p.buckettype as buckettype
  from double_entries_labeled as de
  join proportions_labeled as p 
    on de.bucketid = p.proportionid
  where de.buckettype = "proportion"
union
select
  entryid,
  description,
  cast(amountcents as real) as amountcents,
  bucketid,
  bucketname,
  buckettype
  from double_entries_labeled where buckettype <> "proportion";

drop view if exists double_entries_labeled_expand_proportions_2;
create view double_entries_labeled_expand_proportions_2 as
select entryid, min(description) as description, sum(amountcents) as amountcents, bucketid, min(bucketname) as bucketname, min(buckettype) as buckettype from double_entries_labeled_expand_proportions group by entryid, bucketid;

drop view if exists entries_with_bucket_changes;
create view entries_with_bucket_changes as
select
  t1.entryid as entryid,
  bucketid_for_change,
  case when de.amountcents isnull then 0.0 else de.amountcents end as amountcents
from
  (select entryid, buckets.bucketid as bucketid_for_change
    from entries_labeled as e, buckets where buckets.buckettype = "internal") as t1
  left outer join
  double_entries_labeled_expand_proportions_2 as de
  on t1.entryid = de.entryid and t1.bucketid_for_change = de.bucketid;

drop view if exists net_change;
create view net_change as
select
  bucketid,
  sum(amountcents) as net_change_fractional,
  cast(round(sum(amountcents)) as integer) as net_change
from double_entries_labeled_expand_proportions
group by bucketid;

drop view if exists buckets_with_net_change;
create view buckets_with_net_change as
select 
  b.bucketid as bucketid,
  b.bucketname as bucketname,
  b.buckettype as buckettype,
  b.initialbalancecents as initialbalancecents,
  case when nc.net_change isnull then 0 else nc.net_change end as net_change,
  case when nc.net_change isnull then initialbalancecents else initialbalancecents + nc.net_change end as finalbalancecents
from buckets as b
  left outer join net_change as nc
    on b.bucketid = nc.bucketid
where b.buckettype <> "proportion";

drop view if exists bucket_proportion_combos;
create view bucket_proportion_combos as
select
  bid, bname, pid, pname,
  case when percent isnull then 0 else percent end as percent
from
  (select b.bucketid as bid, b.bucketname as bname, p.bucketid as pid, p.bucketname as pname from
    (select * from buckets where buckettype = "internal") as b,
    (select * from buckets where buckettype = "proportion") as p )
  left outer join proportions_labeled
  on bid = proportionbucketid and pid = proportionid;
