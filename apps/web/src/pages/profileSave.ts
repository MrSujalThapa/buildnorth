export type ProfileFields = { display_name: string; username: string; bio: string };

export async function saveProfileWithPhoto(
  next: ProfileFields,
  previous: ProfileFields,
  saveDetails: (fields: ProfileFields) => Promise<unknown>,
  photoAction?: () => Promise<unknown>,
): Promise<void> {
  await saveDetails(next);
  if (!photoAction) return;
  try {
    await photoAction();
  } catch (error) {
    try {
      await saveDetails(previous);
    } catch {
      throw new Error("Photo failed and profile details may have changed. Reload to review before closing.", { cause: error });
    }
    throw error;
  }
}
