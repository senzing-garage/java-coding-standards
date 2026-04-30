public class Foo
{
    public void method()
    {
        for (int readCount = source.read(buf);
             readCount >= 0;
             readCount = source.read(buf))
        {
            sink.write(buf, 0, readCount);
        }
    }
}
