public class Demo
{
    public void run(java.io.InputStream source, byte[] buffer)
    {
        try {
            if (source != null) {
                for (int readCount = source.read(buffer);
                     readCount >= 0;
                     readCount = source.read(buffer))
                {
                    process(buffer, 0, readCount);
                }
            }
        } catch (java.io.IOException e) {
            throw new RuntimeException(e);
        }
    }
}
