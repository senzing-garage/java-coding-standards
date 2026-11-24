public class Demo
{
    void load(String initFile, Exception e)
    {
        if (initFile != null) {
            if (e != null) {
                if (initFile.length() > 0) {
                    if (e.getMessage() != null) {
                        throw new RuntimeException(
                            multilineFormat(
                                "Failed to read JSON initialization "
                                + "file: " + initFile,
                                "",
                                "Cause: " + e.getMessage()));
                    }
                }
            }
        }
    }
}
