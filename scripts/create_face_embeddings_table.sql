-- Run this SQL in Supabase SQL Editor to create the embeddings table.

create table if not exists face_embeddings (
  student_id int primary key,
  embedding jsonb
);

-- Create an index to speed up lookups if needed
create index if not exists idx_face_embeddings_student_id on face_embeddings(student_id);
